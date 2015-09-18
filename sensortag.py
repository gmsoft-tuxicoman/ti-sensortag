#!/usr/bin/python2

import rrdtool
import argparse
import sys, os

import time
import dbus
import dbus.mainloop.glib
from gi.repository import GObject

import threading

argparser = argparse.ArgumentParser(description="Monitor the TI sensortag")
argparser.add_argument('--dev', '-d', dest='dev_addr', help="Device address", required=True)
argparser.add_argument('--interval', '-i', dest='interval', help='Polling interval in seconds', type=int, default=120)
argparser.add_argument('--rrd', '-r', dest='rrd', help='RRD file', default='sensortag.rrd')
args = argparser.parse_args()

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
bus = dbus.SystemBus()

adapt = {}
devices = {}
dev_path = ''
dev_char = {}


def sensor_rrd_create():
	steps = args.interval # 2 minute steps
	heartbeat = 2 # 2 steps heartbeat

	rrd_heartbeat = str(steps * heartbeat)
	sources = [
		[ "temp", -40, 125 ],
		[ "humidity", 0 , 100],
		[ "lux", 0, 83000 ]
	]
	periods = [
		[ 2 * 60, 48 ], # 2 min resolution for 48 hours
		[ 20 * 60, 24 * 31 ], # 20 min resultion for one month
		[ 60 * 60, 24 * 365 * 5 ] # one hour resolution for 5 years
	]

	rra = [ "MIN", "MAX", "AVERAGE", "LAST" ]

	rrd_src = []
	for s in sources:
		rrd_src.append("DS:" + s[0] + ":GAUGE:" + rrd_heartbeat + ":" + str(s[1]) + ":" + str(s[2]))

	rrd_rra = []
	for p in periods:
		s = int(p[0] / steps)
		rows = int(p[1] * 60 * 60 / steps)
		for r in rra:
			rrd_rra.append("RRA:" + r + ":0.5:" + str(s) + ":" + str(rows))

	print("Creating " + args.rrd + " with " + str(steps) + " seconds steps")
	rrdtool.create(args.rrd, '--step', str(steps), rrd_src, rrd_rra)


def monitor():

	threading.Timer(args.interval, monitor).start()

	for s in sensors:
		sensor = sensors[s]

		if not sensor['monitor']:
			continue
		# Read the value
		sensor['read_func'](sensor['data_uuid'])

def sensor_humidity_temp_read(uuid):
	proxy = dev_char[uuid]['proxy']
	val = proxy.ReadValue()
	tempRaw = val[0] + (val[1] << 8)
	temp = -40.0 + 165.0/65536 * float(tempRaw)
	print("Temperature : " + str(temp))

	humidityRaw = val[2] + (val[3] << 8)
	humidityRaw -= humidityRaw % 4
	humidity = 100.0/65536 * float(humidityRaw)
	print("Humidity : " + str(humidity) + "%")
	rrd_update = [args.rrd, '-t', 'temp:humidity', 'N:' + str(temp) + ':' + str(humidity) ]
	print(rrd_update)
	rrdtool.update(rrd_update)

def sensor_luxometer_read(uuid):
	proxy = dev_char[uuid]['proxy']
	val = proxy.ReadValue()
	lightRaw = val[0] + (val[1] << 8)
	m = lightRaw & 0x0FFF
	e = (lightRaw & 0xF000) >> 12
	lux = m * (0.01 * pow(2.0,e))
	print("Luxometer : " + str(lux) + " lux")
	rrd_update = [args.rrd, '-t', 'lux', 'N:' + str(lux)]
	print(rrd_update)
	rrdtool.update(rrd_update)

sensors = {}
sensors['humidity_temp'] = {
	'name' : 'humidity/temperature',
	'monitor': True,
	'period_uuid' : 'f000aa23-0451-4000-b000-000000000000',
	'config_uuid': 'f000aa22-0451-4000-b000-000000000000',
	'data_uuid' : 'f000aa21-0451-4000-b000-000000000000',
	'read_func' : sensor_humidity_temp_read }

sensors['luxometer'] = {
	'name' : 'luxometer',
	'monitor': True,
	'period_uuid' : 'f000aa73-0451-4000-b000-000000000000',
	'config_uuid': 'f000aa72-0451-4000-b000-000000000000',
	'data_uuid' : 'f000aa71-0451-4000-b000-000000000000',
	'read_func' : sensor_luxometer_read }

def sensors_init():

	poll_period = args.interval * 100
	if poll_period > 255:
		poll_period = 255

	sensors_configured = 0
	while sensors_configured < len(sensors):
		for s in sensors:
			sensor = sensors[s]

			config_proxy = dev_char[sensor['config_uuid']]['proxy']
			if not 'enabled' in sensor:
				# Fetch the state of the sensor
				try:
					val = config_proxy.ReadValue()
				except dbus.exceptions.DBusException as e:
					print("Unable to read sensor config : " + str(e))
					time.sleep(1)
					continue
				if val[0] > 0:
					sensor['enabled'] = True
				else:
					sensor['enabled'] = False

			if sensor['monitor'] != sensor['enabled']:
				# Make sure the sensor is enabled/disabled
				if sensor['monitor']:
					print("Enabling " + sensor['name'] + " sensor")
					val = True
				else:
					print("Disabling " + sensor['name'] + " sensor")
					val = False
				config_proxy.WriteValue([val])
				sensor['enabled'] = val


				print("Sensor " + sensor['name'] + " configured")
				if sensor['monitor']:
					# Update period
					period_uuid = sensor['period_uuid']
					period_proxy = dev_char[period_uuid]['proxy']
					print("Updating polling period to " + str(poll_period) + " for " + sensor['name'] + " sensor")
					period_proxy.WriteValue([poll_period])
				sensors_configured += 1

	# Wait one period for the firmware to fetch all values
	time.sleep(int(poll_period / 100) + 1)

	# Start monitoring
	print("All sensors configured, starting monitoring ...")
	monitor()

def find_adapters():

	adapts = {}
	objs = obj_mgr.GetManagedObjects()
	for obj_path in objs:
	    
		obj = objs[obj_path]
		if 'org.bluez.Adapter1' in obj:
			adapts[obj_path] = obj['org.bluez.Adapter1']

	return adapts

def find_devices():
	devs = {}
	objs = obj_mgr.GetManagedObjects()
	for obj_path in objs:

		obj = objs[obj_path]
		if not 'org.bluez.Device1' in obj:
			# This is not a device
			continue

		if obj_path in devices:
			# We already know about that device
			continue

		addr = obj['org.bluez.Device1']['Address']
		print("Found device " + obj_path + " with addess " + addr)
		devices[obj_path] = obj['org.bluez.Device1']
		if addr != args.dev_addr:
			# This is no the droid^Wdevice we are looking for
			continue

		global dev_path
		dev_path = obj_path

		adapt.StopDiscovery()

		if not obj['org.bluez.Device1']['Connected']:
			dev_connect()
		else:
			print("Already connected connected to " + addr)
			dev_char_update(objs)

	return devs

def dev_connect():
	print("Connecting to " + dev_path + " ...")
	dev = dbus.Interface(bus.get_object("org.bluez", dev_path), 'org.bluez.Device1')
	dev.Connect()

def dev_disconnect():
	if len(dev_path) > 0:
		print("Disconnecting from " + dev_path)
		dev = dbus.Interface(bus.get_object("org.bluez", dev_path), 'org.bluez.Device1')
		dev.Disconnect()

def dev_connected(path):
	print("Connected !")
	if not path in objs:
		print("Could not find device " + path)
		return
	obj = objs[path]
	print(obj)

def dev_char_update(objs):
	print("Updating device characteristics ...")
	for obj_path in objs:
		obj = objs[obj_path]
		if not 'org.bluez.GattCharacteristic1' in obj:
			continue

		char = obj['org.bluez.GattCharacteristic1']

		if not char['Service'].startswith(dev_path):
			continue

		uuid = char['UUID']

		print("Found characteristic : " + char['UUID'] + " with path " + obj_path)
		dev_char[uuid] = {}
		dev_char[uuid]['path'] = obj_path
		dev_char[uuid]['proxy'] = dbus.Interface(bus.get_object("org.bluez", obj_path), 'org.bluez.GattCharacteristic1')

	sensors_init()

def sig_interface_added(path, interface):
	find_devices()

def sig_interface_removed(path, interface):
	if path in devices:
		print ("Device " + path + " gone")
		del devices[path]

def sig_properties_changed(interface, changed, invalidated, path):
	if interface != 'org.bluez.Device1':
		return

	print(str(interface) + " " + str(changed) + " " + str(invalidated) + " " + str(path))

	for prop in changed:
		if prop == 'Connected':
			if changed[prop]:
				print("Connected !")
				dev_char_update(obj_mgr.GetManagedObjects())
			else:
				print("Disconnected !")

		elif prop == 'Name':
			print("Connected to " + changed[prop])
		elif prop == 'GattServices':
			dev_char_update(obj_mgr.GetManagedObjects())



def main():

	if not os.path.isfile(args.rrd):
		sensor_rrd_create()

	global obj_mgr
	obj_mgr = dbus.Interface(bus.get_object("org.bluez", "/"), 'org.freedesktop.DBus.ObjectManager')

	adapts = find_adapters()
	for a in adapts:
		print("Found adapter " + a + " with address " +  adapts[a]['Address'])


	# For now use the first adapter
	adapt_path, adapt_obj  = adapts.popitem()

	# Power it on
	if not adapt_obj['Powered']:
		print("Turning on adapter " + adapt_path)
		adapt_prop = dbus.Interface(bus.get_object("org.bluez", adapt_path), "org.freedesktop.DBus.Properties")
		adapt_prop.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(1))


	# Setup the sig handler

	bus.add_signal_receiver(sig_interface_added, dbus_interface='org.freedesktop.DBus.ObjectManager', signal_name = "InterfacesAdded")
	bus.add_signal_receiver(sig_interface_removed, dbus_interface='org.freedesktop.DBus.ObjectManager', signal_name = "InterfacesRemoved")
	bus.add_signal_receiver(sig_properties_changed, dbus_interface='org.freedesktop.DBus.Properties', signal_name = "PropertiesChanged", arg0 = "org.bluez.Device1", path_keyword = "path")

	global adapt
	adapt = dbus.Interface(bus.get_object("org.bluez", adapt_path), "org.bluez.Adapter1")

	adapt.StartDiscovery()
	find_devices()

	mainloop = GObject.MainLoop()
	mainloop.run()

if __name__ == '__main__':
	try:
		main()
	except KeyboardInterrupt:
		print('Interrupted')
		dev_disconnect()
		try:
			sys.exit(0)
		except SystemExit:
			os._exit(0)

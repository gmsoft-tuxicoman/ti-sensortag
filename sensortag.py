#!/usr/bin/python3



import argparse

import dbus
import dbus.mainloop.glib
from gi.repository import GObject

import threading

argparser = argparse.ArgumentParser(description="Monitor the TI sensortag")
argparser.add_argument('--dev', '-d', dest='dev_addr', help="Device address", required=True)
args = argparser.parse_args()

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
bus = dbus.SystemBus()

devices = {}
dev_path = ''
dev_char = {}

monitor = {}
monitor['humidity_temp'] = True

SENSOR_HUMIDITY_TEMP_CONFIG_UUID = 'f000aa22-0451-4000-b000-000000000000'
SENSOR_HUMIDITY_TEMP_DATA_UUID = 'f000aa21-0451-4000-b000-000000000000'
SENSOR_HUMIDITY_TEMP_PERIOD_UUID = 'f000aa23-0451-4000-b000-000000000000'


def monitor():
	threading.Timer(1.0, monitor).start()

	sensor_humidity_temp_read()

def sensor_humidity_temp_config():
	proxy = dev_char[SENSOR_HUMIDITY_TEMP_CONFIG_UUID]['proxy']
	val = proxy.ReadValue()
	print("Value : " + str(val))
	if val[0] == 0:
		print("Enabling humidity/temperature sensor")
		proxy.WriteValue([1])

def sensor_humidity_temp_read():
	proxy = dev_char[SENSOR_HUMIDITY_TEMP_DATA_UUID]['proxy']
	val = proxy.ReadValue()
	tempRaw = val[0] + (val[1] << 8)
	temp = -40.0 + 165.0/65536 * float(tempRaw)
	print("Temperature : " + str(temp))

	humidityRaw = val[2] + (val[3] << 8)
	humidityRaw -= humidityRaw % 4
	humidity = 100.0/65536 * float(humidityRaw)
	print("Humidity : " + str(humidity) + "%")


sensor_char = {
	SENSOR_HUMIDITY_TEMP_CONFIG_UUID : sensor_humidity_temp_config,
	SENSOR_HUMIDITY_TEMP_DATA_UUID : sensor_humidity_temp_read
}

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

		dev_path = obj_path

		if not obj['org.bluez.Device1']['Connected']:
			dev_connect(obj_path)
		else:
			print("Already connected connected to " + addr)

		# bluez caches service, it may already know about it
		if 'GattServices' in obj['org.bluez.Device1']:
			dev_char_update(objs)
	return devs

def dev_connect(path):
	print("Connecting to " + path)
	dev = dbus.Interface(bus.get_object("org.bluez", path), 'org.bluez.Device1')
	dev.Connect()

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

		if uuid in sensor_char:
			sensor_char[uuid]()
	monitor()

def sig_interface_added(path, interface):
	find_devices()

def sig_interface_removed(path, interface):
	if path in devices:
		print ("Device " + path + " gone")
		del devices[path]

def sig_properties_changed(interface, changed, invalidated, path):
	if interface != 'org.bluez.Device1':
		return

	# print(str(interface) + " " + str(changed) + " " + str(invalidated) + " " + str(path))

	for prop in changed:
		if prop == 'Connected':
			if changed[prop]:
				print("Connected !")
			else:
				print("Disconnected !")
		elif prop == 'GattServices':
			dev_char_update(obj_mgr.GetManagedObjects())



if __name__ == '__main__':

	global obj_mgr
	obj_mgr = dbus.Interface(bus.get_object("org.bluez", "/"), 'org.freedesktop.DBus.ObjectManager')

	adapts = find_adapters()
	for a in adapts:
		print("Found adapter " + a + " with address " +  adapts[a]['Address'])


	# For now use the first adapter
	adapt_path, adapt_obj  = adapts.popitem()

	# Power it on
	if not adapt_obj['Powered']:
		adapt_prop = dbus.Interface(bus.get_object("org.bluez", adapt_path), "org.freedesktop.DBus.Properties")
		adapt_prop.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(1))
		print("Turned on adapter " + adapt_path)


	# Setup the sig handler

	bus.add_signal_receiver(sig_interface_added, dbus_interface='org.freedesktop.DBus.ObjectManager', signal_name = "InterfacesAdded")
	bus.add_signal_receiver(sig_interface_removed, dbus_interface='org.freedesktop.DBus.ObjectManager', signal_name = "InterfacesRemoved")
	bus.add_signal_receiver(sig_properties_changed, dbus_interface='org.freedesktop.DBus.Properties', signal_name = "PropertiesChanged", arg0 = "org.bluez.Device1", path_keyword = "path")

	adapt = dbus.Interface(bus.get_object("org.bluez", adapt_path), "org.bluez.Adapter1")

	find_devices()
	adapt.StartDiscovery()

	mainloop = GObject.MainLoop()
	mainloop.run()


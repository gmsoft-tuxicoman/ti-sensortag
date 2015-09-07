#!/usr/bin/python3



import argparse

import dbus
import dbus.mainloop.glib
from gi.repository import GObject

argparser = argparse.ArgumentParser(description="Monitor the TI sensortag")
argparser.add_argument('--dev', '-d', dest='dev_addr', help="Device address")
args = argparser.parse_args()

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
bus = dbus.SystemBus()

devices = {}


def handle_uuids(uuids):
	for uuid in uuids:
		print("Found UUID " + uuid)

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

		if not obj['org.bluez.Device1']['Connected']:
			print("Connecting to " + addr)
			dev_connect(obj_path)
		else:
			print("Already connected to " + addr)
			handle_uuids(obj['org.bluez.Device1']['UUIDs'])
	return devs

def dev_connect(path):
	dev = dbus.Interface(bus.get_object("org.bluez", path), 'org.bluez.Device1')
	dev.Connect()

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
		print("Property : " + prop)

		if prop == 'Connected':
			if changed[prop]:
				print("Connected !")
			else:
				print("Disconnected !")
		elif prop == 'UUIDs':
			handle_uuids(changed[prop])





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


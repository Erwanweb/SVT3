"""
Smart Virtual Thermostat FOR trv python plugin for Domoticz
Author: Erwanweb,
        adapted from the SVT By Logread V0.4.4 and Anthor, see:
            https://github.com/999LV/SmartVirtualThermostat
            http://www.antor.fr/apps/smart-virtual-thermostat-eng-2/?lang=en
            https://github.com/AntorFr/SmartVT
Version:    0.0.1: alpha
            0.0.2: beta
            0.1.1: correction for reducted temp if no presence
            0.1.2: correction for control of TRV setpoint
"""
"""
<plugin key="SVT3" name="AC Smart Virtual Thermostat for TRV" author="Erwanweb" version="0.1.2" externallink="https://github.com/Erwanweb/SVT3.git">
    <description>
        <h2>Smart Virtual Thermostat for TRV</h2><br/>
        V.0.1.2<br/>
        Easily implement in Domoticz an advanced virtual thermostat using TRV<br/>
        <h3>Set-up and Configuration</h3>
    </description>
    <params>
        <param field="Address" label="Domoticz IP Address" width="200px" required="true" default="127.0.0.1"/>
        <param field="Port" label="Port" width="40px" required="true" default="8080"/>
        <param field="Username" label="Username" width="200px" required="false" default=""/>
        <param field="Password" label="Password" width="200px" required="false" default=""/>
        <param field="Mode1" label="Inside Temperature Sensors (csv list of idx)" width="100px" required="true" default="0"/>
        <param field="Mode2" label="TRV Temperature Sensors (csv list of idx)" width="100px" required="false" default=""/>
        <param field="Mode3" label="TRV (csv list of idx)" width="100px" required="true" default="0"/>
        <param field="Mode4" label="Presence Sensors (csv list of idx)" width="100px" required="false" default=""/>
        <param field="Mode5" label="Pause On delay, Pause Off delay, Forced mode duration (all in minutes) reduc jour, reduc nuit (both in tenth of degre)" width="200px" required="true" default="2,1,60,1,60,10,20"/>
        <param field="Mode6" label="Logging Level" width="200px">
            <options>
                <option label="Normal" value="Normal"  default="true"/>
                <option label="Verbose" value="Verbose"/>
                <option label="Debug - Python Only" value="2"/>
                <option label="Debug - Basic" value="62"/>
                <option label="Debug - Basic+Messages" value="126"/>
                <option label="Debug - Connections Only" value="16"/>
                <option label="Debug - Connections+Queue" value="144"/>
                <option label="Debug - All" value="-1"/>
            </options>
        </param>
    </params>
</plugin>
"""
import Domoticz
import json
import urllib.parse as parse
import urllib.request as request
from datetime import datetime, timedelta
import time
import base64
import itertools

class deviceparam:

    def __init__(self, unit, nvalue, svalue):
        self.unit = unit
        self.nvalue = nvalue
        self.svalue = svalue


class BasePlugin:

    def __init__(self):

        self.debug = False
        self.pauseondelay = 2  # time between pause sensor actuation and actual pause
        self.pauseoffdelay = 1  # time between end of pause sensor actuation and end of actual pause
        self.forcedduration = 60  # time in minutes for the forced mode
        self.ActiveSensors = {}
        self.InTempSensors = []
        self.TRVTempSensors = []
        self.OutTempSensors = []
        self.switchHeat = False
        self.Heaters = []
        self.heat = False
        self.pause = False
        self.pauserequested = False
        self.pauserequestchangedtime = datetime.now()
        self.forced = False
        self.intemp = 20.0
        self.intemperror = False
        self.TRVtemp = 20.0
        self.outtemp = 20.0
        self.setpoint = 20.0
        self.TRVsetpoint = 20.0
        self.endheat = datetime.now()
        self.nexttemps = self.endheat
        self.DTpresence = []
        self.Presencemode = False
        self.Presence = False
        self.PresenceTH = False
        self.presencechangedtime = datetime.now()
        self.PresenceDetected = False
        self.DTtempo = datetime.now()
        self.presenceondelay = 1  # time between first detection and last detection before turning presence ON
        self.presenceoffdelay = 60  # time between last detection before turning presence OFF
        self.reducjour = 10  # reduction de la temp par rapport a la consigne
        self.reducnuit = 20  # reduction de la temp par rapport a la consigne
        self.learn = True
        return


    def onStart(self):

        # setup the appropriate logging level
        try:
            debuglevel = int(Parameters["Mode6"])
        except ValueError:
            debuglevel = 0
            self.loglevel = Parameters["Mode6"]
        if debuglevel != 0:
            self.debug = True
            Domoticz.Debugging(debuglevel)
            DumpConfigToLog()
            self.loglevel = "Verbose"
        else:
            self.debug = False
            Domoticz.Debugging(0)

        # create the child devices if these do not exist yet
        devicecreated = []
        if 1 not in Devices:
            Options = {"LevelActions": "||",
                       "LevelNames": "Off|Auto|Forced",
                       "LevelOffHidden": "false",
                       "SelectorStyle": "0"}
            Domoticz.Device(Name="Thermostat Control", Unit=1, TypeName="Selector Switch", Switchtype=18, Image=15,
                            Options=Options, Used=1).Create()
            devicecreated.append(deviceparam(1, 0, "0"))  # default is Off state
        if 2 not in Devices:
            Options = {"LevelActions": "||",
                       "LevelNames": "Off|Normal|Economy|Vacation",
                       "LevelOffHidden": "true",
                       "SelectorStyle": "0"}
            Domoticz.Device(Name="Thermostat Mode", Unit=2, TypeName="Selector Switch", Switchtype=18, Image=15,
                            Options=Options, Used=1).Create()
            devicecreated.append(deviceparam(2, 0, "10"))  # default is normal confort mode
        if 3 not in Devices:
            Domoticz.Device(Name="Thermostat Pause", Unit=3, TypeName="Switch", Image=9, Used=1).Create()
            devicecreated.append(deviceparam(3, 0, ""))  # default is Off
        if 4 not in Devices:
            Domoticz.Device(Name="Setpoint Normal", Unit=4, Type=242, Subtype=1, Used=1).Create()
            devicecreated.append(deviceparam(4, 0, "20"))  # default is 20 degrees
        if 5 not in Devices:
            Domoticz.Device(Name="Setpoint Economy", Unit=5, Type=242, Subtype=1).Create()
            devicecreated.append(deviceparam(5 ,0, "18"))  # default is 18 degrees
        if 6 not in Devices:
            Domoticz.Device(Name="Thermostat temp", Unit=6, TypeName="Temperature", Used=1).Create()
            devicecreated.append(deviceparam(6, 0, "20"))  # default is 20 degrees
        if 7 not in Devices:
            Domoticz.Device(Name="Heating Request", Unit=7, TypeName="Switch", Image=9, Used=1).Create()
            devicecreated.append(deviceparam(7, 0, ""))  # default is Off
        if 8 not in Devices:
            Domoticz.Device(Name="Presence sensor", Unit=8, TypeName="Switch", Image=9).Create()
            devicecreated.append(deviceparam(8, 0, ""))  # default is Off

        # if any device has been created in onStart(), now is time to update its defaults
        for device in devicecreated:
            Devices[device.unit].Update(nValue=device.nvalue, sValue=device.svalue)

        # build lists of sensors and switches
        self.InTempSensors = parseCSV(Parameters["Mode1"])
        Domoticz.Debug("Inside Temperature sensors = {}".format(self.InTempSensors))
        self.TRVTempSensors = parseCSV(Parameters["Mode2"])
        Domoticz.Debug("TRV Temperature sensors = {}".format(self.TRVTempSensors))
        self.Heaters = parseCSV(Parameters["Mode3"])
        Domoticz.Debug("Heaters = {}".format(self.Heaters))
        self.DTpresence = parseCSV(Parameters["Mode4"])
        Domoticz.Debug("DTpresence = {}".format(self.DTpresence))

        # build dict of status of all temp sensors to be used when handling timeouts
        for sensor in itertools.chain(self.InTempSensors, self.TRVTempSensors):
            self.ActiveSensors[sensor] = True

        # splits additional parameters
        params = parseCSV(Parameters["Mode5"])
        if len(params) == 7:
            self.pauseondelay = CheckParam("Pause On Delay", params[0], 2)
            self.pauseoffdelay = CheckParam("Pause Off Delay", params[1], 0)
            self.forcedduration = CheckParam("Forced Mode Duration", params[2], 60)
            if self.forcedduration < 30:
                Domoticz.Error("Invalid forced mode duration parameter. Using minimum of 30 minutes !")
                self.calculate_period = 30
            self.presenceondelay = CheckParam("Presence On Delay", params[3], 1)
            self.presenceoffdelay = CheckParam("Presence Off Delay",params[4],30)
            self.reducjour = CheckParam("reduit jour",params[5],10)
            self.reducnuit = CheckParam("reduit nuit",params[6],20)
        else:
            Domoticz.Error("Error reading Mode5 parameters")

        # if mode = off then make sure actual heating is off just in case if was manually set to on
        if Devices[1].sValue == "0":
            self.switchHeat = False


    def onStop(self):

        Domoticz.Debugging(0)


    def onCommand(self, Unit, Command, Level, Color):

        Domoticz.Debug("onCommand called for Unit {}: Command '{}', Level: {}".format(Unit, Command, Level))

        if Unit == 3:  # pause switch
            self.pauserequestchangedtime = datetime.now()
            svalue = ""
            if str(Command) == "On":
                nvalue = 1
                self.pauserequested = True
            else:
                nvalue = 0
                self.pauserequested = False

        else:
            nvalue = 1 if Level > 0 else 0
            svalue = str(Level)

        Devices[Unit].Update(nValue=nvalue, sValue=svalue)

        if Unit in (1, 2, 4, 5): # truc
            self.onHeartbeat()


    def onHeartbeat(self):

        self.PresenceDetection()

        now = datetime.now()

        # fool proof checking.... based on users feedback
        if not all(device in Devices for device in (1,2,3,4,5,6,7,8)):
            Domoticz.Error("one or more devices required by the plugin is/are missing, please check domoticz device creation settings and restart !")
            return


        if Devices[1].sValue == "0":  # Thermostat is off
            Domoticz.Log("Thermostat is OFF")

            if self.forced or self.switchHeat:  # thermostat setting was just changed so we kill the heating
                self.forced = False
                self.switchHeat = False
                Domoticz.Debug("Switching heat Off !")
                Domoticz.Debug("TRV Calculded setpoint is : 7")
                self.TRVsetpoint = 7
                if not Devices[7].nValue == 0:
                    Devices[7].Update(nValue = 0,sValue = Devices[7].sValue)

        elif Devices[1].sValue == "20":  # Thermostat is in forced mode
            Domoticz.Log("Thermostat is in FORCED mode")

            if self.forced:
                if self.endheat <= now:
                    self.forced = False
                    self.endheat = now
                    Domoticz.Debug("Forced mode Off after timer !")
                    Devices[1].Update(nValue=1, sValue="10")  # set thermostat to normal mode
                    self.switchHeat = False
                    self.TRVsetpoint = self.setpoint + (self.intemp - self.TRVtemp)  # correction of TRV setpoint using difference between real indoor temp and mesured trv temp.
                    Domoticz.Debug("TRV Calculded setpoint is : " + str(self.TRVsetpoint))
                    if not Devices[7].nValue == 0:
                        Devices[7].Update(nValue = 0,sValue = Devices[7].sValue)
            else:
                self.forced = True
                self.endheat = now + timedelta(minutes=self.forcedduration)
                Domoticz.Debug("Forced mode On !")
                self.switchHeat = True
                Domoticz.Debug("TRV Calculded setpoint is : 28")
                self.TRVsetpoint = 28
                if Devices[7].nValue == 0:
                    Devices[7].Update(nValue = 1,sValue = Devices[7].sValue)

        else:  # Thermostat is in mode auto
            Domoticz.Debug("Thermostat is in AUTO mode")

            if self.forced:  # thermostat setting was just changed from "forced" so we kill the forced mode
                Domoticz.Debug("Forced mode Off !")
                self.forced = False
                self.switchHeat = True
                self.TRVsetpoint = self.setpoint + (self.intemp - self.TRVtemp)  # correction of TRV setpoint using difference between real indoor temp and mesured trv temp.
                Domoticz.Debug("TRV Calculded setpoint is : " + str(self.TRVsetpoint))
                if not Devices[7].nValue == 0:
                    Devices[7].Update(nValue = 0,sValue = Devices[7].sValue)

            elif self.pause and not self.pauserequested:  # we are in pause and the pause switch is now off
                if self.pauserequestchangedtime + timedelta(minutes=self.pauseoffdelay) <= now:
                    Domoticz.Debug("Pause is now Off")
                    self.pause = False
                    self.switchHeat = True
                    self.TRVsetpoint = self.setpoint + (self.intemp - self.TRVtemp)  # correction of TRV setpoint using difference between real indoor temp and mesured trv temp.
                    Domoticz.Debug("TRV Calculded setpoint is : " + str(self.TRVsetpoint))

            elif not self.pause and self.pauserequested:  # we are not in pause and the pause switch is now on
                if self.pauserequestchangedtime + timedelta(minutes=self.pauseondelay) <= now:
                    Domoticz.Debug("Pause is now On")
                    self.pause = True
                    self.switchHeat = False
                    Domoticz.Debug("TRV Calculded setpoint is : 5")
                    self.TRVsetpoint = 5
                    if not Devices[7].nValue == 0:
                        Devices[7].Update(nValue = 0,sValue = Devices[7].sValue)

            else: # thermostart is ok in auto mode

                self.switchHeat = True

                # make current setpoint used in calculation reflect the select mode (10= normal, 20 = economy)

                if Devices[2].sValue == "10":  # Mode Auto
                    if self.PresenceTH:
                        self.setpoint = float(Devices[4].sValue)
                        Domoticz.Log("AUTO Mode - used setpoint is NORMAL : " + str(self.setpoint))
                        self.TRVsetpoint = self.setpoint + (self.intemp - self.TRVtemp)  # correction of TRV setpoint using difference between real indoor temp and mesured trv temp.
                        Domoticz.Debug("TRV Calculded setpoint is : " + str(self.TRVsetpoint))

                    else:
                        self.setpoint = (float(Devices[4].sValue) - ((self.reducjour) / 10))
                        Domoticz.Log("AUTO Mode - used setpoint is reducted one : " + str(self.setpoint))
                        self.TRVsetpoint = self.setpoint + (self.intemp - self.TRVtemp)  # correction of TRV setpoint using difference between real indoor temp and mesured trv temp.
                        Domoticz.Debug("TRV Calculded setpoint is : " + str(self.TRVsetpoint))

                elif Devices[2].sValue == "20":  # Mode ECO
                    self.setpoint = float(Devices[5].sValue)
                    Domoticz.Log("ECO Mode - used setpoint is ECO one : " + str(self.setpoint))
                    self.TRVsetpoint = self.setpoint + (self.intemp - self.TRVtemp)  # correction of TRV setpoint using difference between real indoor temp and mesured trv temp.
                    Domoticz.Debug("TRV Calculded setpoint is : " + str(self.TRVsetpoint))

                else:
                    self.setpoint = 15  # Mode Vacances
                    Domoticz.Log("VACATION Mode - used setpoint is VACATION one : " + str(self.setpoint))
                    self.TRVsetpoint = self.setpoint + (self.intemp - self.TRVtemp)  # correction of TRV setpoint using difference between real indoor temp and mesured trv temp.
                    Domoticz.Debug("TRV Calculded setpoint is : " + str(self.TRVsetpoint))


        # we check if not int temp error and if heating is requested and turn on or off the heating request device
        if not self.forced:
            if not self.intemperror :
                if self.switchHeat and self.intemp < self.setpoint:
                    if Devices[7].nValue == 0:
                        Devices[7].Update(nValue = 1,sValue = Devices[7].sValue)
                else:
                    if not Devices[7].nValue == 0:
                        Devices[7].Update(nValue = 0,sValue = Devices[7].sValue)
            else:
                if not Devices[7].nValue == 0:
                    Devices[7].Update(nValue = 0,sValue = Devices[7].sValue)


        if self.nexttemps <= now:
            # call the Domoticz json API for a temperature devices update, to get the lastest temps (and avoid the
            # connection time out time after 10mins that floods domoticz logs in versions of domoticz since spring 2018)
            self.readTemps()
            # we update the TRV Setpoint
            for idx in self.Heaters:
                DomoticzAPI("type=command&param=setsetpoint&idx={}&setpoint={}".format(idx,self.TRVsetpoint))
                Domoticz.Log("TRV Calculded setpoint is : " + str(self.TRVsetpoint))


    def PresenceDetection(self):

        now = datetime.now()

        if Parameters["Mode4"] == "":
            Domoticz.Debug("presence detection mode = NO...")
            self.Presencemode = False
            self.Presence = False
            self.PresenceTH = True
            if not Devices[8].nValue == 0:
                Devices[8].Update(nValue = 0,sValue = Devices[8].sValue)

        else:
            self.Presencemode = True
            Domoticz.Debug("presence detection mode = YES...")


            # Build list of DT switches, with their current status
            PresenceDT = {}
            devicesAPI = DomoticzAPI("type=devices&filter=light&used=true&order=Name")
            if devicesAPI:
                for device in devicesAPI["result"]:  # parse the presence/motion sensors (DT) device
                    idx = int(device["idx"])
                    if idx in self.DTpresence:  # this is one of our DT
                        if "Status" in device:
                            PresenceDT[idx] = True if device["Status"] == "On" else False
                            Domoticz.Debug("DT switch {} currently is '{}'".format(idx,device["Status"]))
                            if device["Status"] == "On":
                                self.DTtempo = datetime.now()

                        else:
                            Domoticz.Error("Device with idx={} does not seem to be a DT !".format(idx))


            # fool proof checking....
            if len(PresenceDT) == 0:
               Domoticz.Error("none of the devices in the 'dt' parameter is a dt... no action !")
               self.Presencemode = False
               self.Presence = False
               self.PresenceTH = True
               Devices[8].Update(nValue = 0,sValue = Devices[8].sValue)
               return

            if self.DTtempo + timedelta(seconds = 30) >= now:
                self.PresenceDetected = True
                Domoticz.Debug("At mini 1 DT is ON or was ON in the past 30 seconds...")
            else:
                self.PresenceDetected = False


            if self.PresenceDetected:
                if Devices[8].nValue == 1:
                    Domoticz.Debug("presence detected but already registred...")
                else:
                    Domoticz.Debug("new presence detected...")
                    Devices[8].Update(nValue = 1,sValue = Devices[8].sValue)
                    self.Presence = True
                    self.presencechangedtime = datetime.now()

            else:
                if Devices[8].nValue == 0:
                    Domoticz.Debug("No presence detected DT already OFF...")
                else:
                    Domoticz.Debug("No presence detected in the past 30 seconds...")
                    Devices[8].Update(nValue = 0,sValue = Devices[8].sValue)
                    self.Presence = False
                    self.presencechangedtime = datetime.now()


            if self.Presence:
                if not self.PresenceTH:
                    if self.presencechangedtime + timedelta(minutes = self.presenceondelay) <= now:
                        Domoticz.Debug("Presence is now ACTIVE !")
                        self.PresenceTH = True

                    else:
                            Domoticz.Debug("Presence is INACTIVE but in timer ON period !")
                elif self.PresenceTH:
                        Domoticz.Debug("Presence is ACTIVE !")
            else:
                if self.PresenceTH:
                    if self.presencechangedtime + timedelta(minutes = self.presenceoffdelay) <= now:
                        Domoticz.Debug("Presence is now INACTIVE because no DT since more than X minutes !")
                        self.PresenceTH = False

                    else:
                        Domoticz.Debug("Presence is ACTIVE but in timer OFF period !")
                else:
                    Domoticz.Debug("Presence is INACTIVE !")



    def readTemps(self):

        # set update flag for next temp update
        self.nexttemps = datetime.now() + timedelta(minutes=2)

        # fetch all the devices from the API and scan for sensors
        noerror = True
        listintemps = []
        listtrvtemps = []
        devicesAPI = DomoticzAPI("type=devices&filter=temp&used=true&order=Name")
        if devicesAPI:
            for device in devicesAPI["result"]:  # parse the devices for temperature sensors
                idx = int(device["idx"])
                if idx in self.InTempSensors:
                    if "Temp" in device:
                        Domoticz.Debug("device: {}-{} = {}".format(device["idx"], device["Name"], device["Temp"]))
                        # check temp sensor is not timed out
                        if not self.SensorTimedOut(idx, device["Name"], device["LastUpdate"]):
                            listintemps.append(device["Temp"])
                    else:
                        Domoticz.Error("device: {}-{} is not a Temperature sensor".format(device["idx"], device["Name"]))
                elif idx in self.TRVTempSensors:
                    if "Temp" in device:
                        Domoticz.Debug("device: {}-{} = {}".format(device["idx"], device["Name"], device["Temp"]))
                        # check temp sensor is not timed out
                        if not self.SensorTimedOut(idx, device["Name"], device["LastUpdate"]):
                            listtrvtemps.append(device["Temp"])
                    else:
                        Domoticz.Error("device: {}-{} is not a Temperature sensor".format(device["idx"], device["Name"]))

        # calculate the average inside temperature
        nbtemps = len(listintemps)
        if nbtemps > 0:
            self.intemp = round(sum(listintemps) / nbtemps, 1)
            Devices[6].Update(nValue = 0,sValue = str(self.intemp),TimedOut = False)
            if self.intemperror:  # there was previously an invalid inside temperature reading... reset to normal
                self.intemperror = False
                self.WriteLog("Inside Temperature reading is now valid again: Resuming normal operation","Status")
                # we remove the timedout flag on the thermostat switch
                Devices[1].Update(nValue = Devices[1].nValue,sValue = Devices[1].sValue,TimedOut = False)
        else:
            # no valid inside temperature
            noerror = False
            if not self.intemperror:
                self.intemperror = True
                Domoticz.Error("No Inside Temperature found: Switching request heating Off")
                self.switchHeat = False
                # we mark both the thermostat switch and the thermostat temp devices as timedout
                Devices[1].Update(nValue = Devices[1].nValue,sValue = Devices[1].sValue,TimedOut = True)
                Devices[6].Update(nValue = Devices[6].nValue,sValue = Devices[6].sValue,TimedOut = True)

        # calculate the average TRV temperature
        nbtemps = len(listtrvtemps)
        if nbtemps > 0:
            self.TRVtemp = round(sum(listtrvtemps) / nbtemps, 1)
        else:
            Domoticz.Debug("No TRV Temperature found... Using Inside temperature as TRV temp")
            if not self.intemperror:
                self.TRVtemp = self.intemp
            else:
                self.TRVtemp = 25

        self.WriteLog("Inside Temperature = {}".format(self.intemp), "Verbose")
        self.WriteLog("TRV Temperature = {}".format(self.TRVtemp), "Verbose")
        return noerror


    def WriteLog(self, message, level="Normal"):

        if self.loglevel == "Verbose" and level == "Verbose":
            Domoticz.Log(message)
        elif level == "Normal":
            Domoticz.Log(message)

    def SensorTimedOut(self, idx, name, datestring):

        def LastUpdate(datestring):
            dateformat = "%Y-%m-%d %H:%M:%S"
            # the below try/except is meant to address an intermittent python bug in some embedded systems
            try:
                result = datetime.strptime(datestring, dateformat)
            except TypeError:
                result = datetime(*(time.strptime(datestring, dateformat)[0:6]))
            return result

        timedout = LastUpdate(datestring) + timedelta(minutes=int(Settings["SensorTimeout"])) < datetime.now()

        # handle logging of time outs... only log when status changes (less clutter in logs)
        if timedout:
            if self.ActiveSensors[idx]:
                Domoticz.Error("skipping timed out temperature sensor '{}'".format(name))
                self.ActiveSensors[idx] = False
        else:
            if not self.ActiveSensors[idx]:
                Domoticz.Status("previously timed out temperature sensor '{}' is back online".format(name))
                self.ActiveSensors[idx] = True

        return timedout


global _plugin
_plugin = BasePlugin()


def onStart():
    global _plugin
    _plugin.onStart()


def onStop():
    global _plugin
    _plugin.onStop()


def onCommand(Unit, Command, Level, Color):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Color)


def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()


# Plugin utility functions ---------------------------------------------------

def parseCSV(strCSV):

    listvals = []
    for value in strCSV.split(","):
        try:
            val = int(value)
        except:
            pass
        else:
            listvals.append(val)
    return listvals


def DomoticzAPI(APICall):

    resultJson = None
    url = "http://{}:{}/json.htm?{}".format(Parameters["Address"], Parameters["Port"], parse.quote(APICall, safe="&="))
    Domoticz.Debug("Calling domoticz API: {}".format(url))
    try:
        req = request.Request(url)
        if Parameters["Username"] != "":
            Domoticz.Debug("Add authentification for user {}".format(Parameters["Username"]))
            credentials = ('%s:%s' % (Parameters["Username"], Parameters["Password"]))
            encoded_credentials = base64.b64encode(credentials.encode('ascii'))
            req.add_header('Authorization', 'Basic %s' % encoded_credentials.decode("ascii"))

        response = request.urlopen(req)
        if response.status == 200:
            resultJson = json.loads(response.read().decode('utf-8'))
            if resultJson["status"] != "OK":
                Domoticz.Error("Domoticz API returned an error: status = {}".format(resultJson["status"]))
                resultJson = None
        else:
            Domoticz.Error("Domoticz API: http error = {}".format(response.status))
    except:
        Domoticz.Error("Error calling '{}'".format(url))
    return resultJson


def CheckParam(name, value, default):

    try:
        param = int(value)
    except ValueError:
        param = default
        Domoticz.Error("Parameter '{}' has an invalid value of '{}' ! defaut of '{}' is instead used.".format(name, value, default))
    return param


# Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug("'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
    return
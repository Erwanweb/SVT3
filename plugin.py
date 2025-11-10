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
            0.1.3: correction for control of TRV setpoint when off
            2.0.1: adding smart delay for zigbee messages
"""
"""
<plugin key="SVT3" name="AC Smart Virtual Thermostat for TRV" author="Erwanweb" version="2.0.1" externallink="https://github.com/Erwanweb/SVT3.git">
    <description>
        <h2>Smart Virtual Thermostat for TRV</h2><br/>
        V2.0.1<br/>
        Easily implement in Domoticz an advanced virtual thermostat using TRV<br/>
        <h3>Set-up and Configuration</h3>
    </description>
    <params>
        <param field="Mode1" label="Inside Temperature Sensors (csv list of idx)" width="100px" required="true" default="0"/>
        <param field="Mode2" label="TRV Temperature Sensors (csv list of idx)" width="100px" required="false" default=""/>
        <param field="Mode3" label="TRV Actuators (csv list of idx)" width="100px" required="true" default="0"/>
        <param field="Mode4" label="Presence Sensors (csv list of idx)" width="100px" required="false" default=""/>
        <param field="Mode5" label="Pause On delay, Pause Off delay, Forced mode duration, Presence on delay, Presence off delay(all in minutes) reduc jour, reduc nuit (both in tenth of degre)" width="200px" required="true" default="2,1,60,1,60,10,20"/>
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
import random
from datetime import datetime, timedelta
import time
import base64
import itertools
import urllib.error as urlerror


class deviceparam:

    def __init__(self, unit, nvalue, svalue):
        self.unit = unit
        self.nvalue = nvalue
        self.svalue = svalue


class BasePlugin:

    def __init__(self):

        now = datetime.now()  # Time helper

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
        self.pauserequestchangedtime = now
        self.forced = False
        self.intemp = 20.0
        self.intemperror = False
        self.TRVtemp = 20.0
        self.outtemp = 20.0
        self.setpoint = 20.0
        self.TRVsetpoint = 20.0
        self.endheat = now
        self.nexttemps = now
        self.temptimeout = now
        self.DTpresence = []
        self.Presencemode = False
        self.Presence = False
        self.PresenceTH = False
        self.presencechangedtime = now
        self.PresenceDetected = False
        self.DTtempo = now
        self.presenceondelay = 1  # time between first detection and last detection before turning presence ON
        self.presenceoffdelay = 60  # time between last detection before turning presence OFF
        self.reducjour = 10  # reduction de la temp par rapport a la consigne
        self.reducnuit = 20  # reduction de la temp par rapport a la consigne
        self.learn = True
        self.RefreshAndActTime = now
        self.NextInterval = random.randint(60, 90)
        self.PLUGINstarteddtime = now
        self.DTexcludedUntil = {}
        self.TempExcludedUntil = {}
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

        # Set domoticz heartbeat to 20 s (onheattbeat() will be called every 20 )
        Domoticz.Heartbeat(20)

        # reset time info when starting the plugin.
        self.PLUGINstarteddtime = datetime.now()
        self.nexttemps = datetime.now()- timedelta(minutes=5)


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


        now = datetime.now()
        # fool proof checking.... based on users feedback
        if not all(device in Devices for device in (1,2,3,4,5,6,7,8)):
            Domoticz.Error("one or more devices required by the plugin is/are missing, please check domoticz device creation settings and restart !")
            return

        if not self.PLUGINstarteddtime + timedelta(minutes=2) <= now:
            Domoticz.Log( "---> Plugin starting.... Wait a while")  # we wait for Zigbee plugin starting well and all others needed...
            return
        else : # Plugin really started.....
            # update temp
            if self.nexttemps + timedelta(minutes=2) <= now:
                self.readTemps()

        if Devices[1].sValue == "0":  # Thermostat is off
            Domoticz.Log("Thermostat is OFF")
            Domoticz.Debug("TRV Calculded setpoint is : 7 because of thermostat off")
            self.TRVsetpoint = 7
            if not Devices[7].nValue == 0:
                Devices[7].Update(nValue=0, sValue=Devices[7].sValue)

            if self.forced or self.switchHeat:  # thermostat setting was just changed so we kill the heating
                self.forced = False
                self.switchHeat = False
                Domoticz.Debug("Switching heat Off !")


        elif Devices[1].sValue == "20":  # Thermostat is in forced mode
            Domoticz.Log("Thermostat is in FORCED mode")

            if self.forced:
                if self.endheat <= now:
                    self.forced = False
                    self.endheat = now
                    Domoticz.Debug("Forced mode Off after timer !")
                    Devices[1].Update(nValue=1, sValue="10")  # set thermostat to normal mode
                    self.switchHeat = False
                    self.TRVsetpoint = math.ceil(self.setpoint - (self.intemp - self.TRVtemp))  # correction of TRV setpoint using difference between real indoor temp and mesured trv temp.
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
                self.TRVsetpoint = math.ceil(self.setpoint - (self.intemp - self.TRVtemp))   # correction of TRV setpoint using difference between real indoor temp and mesured trv temp.
                Domoticz.Debug("TRV Calculded setpoint is : " + str(self.TRVsetpoint))
                if not Devices[7].nValue == 0:
                    Devices[7].Update(nValue = 0,sValue = Devices[7].sValue)

            elif self.pause and not self.pauserequested:  # we are in pause and the pause switch is now off
                if self.pauserequestchangedtime + timedelta(minutes=self.pauseoffdelay) <= now:
                    Domoticz.Debug("Pause is now Off")
                    self.pause = False
                    self.switchHeat = True
                    self.TRVsetpoint = math.ceil(self.setpoint - (self.intemp - self.TRVtemp))  # correction of TRV setpoint using difference between real indoor temp and mesured trv temp.
                    Domoticz.Debug("TRV Calculded setpoint is : " + str(self.TRVsetpoint))

            elif not self.pause and self.pauserequested:  # we are not in pause and the pause switch is now on
                if self.pauserequestchangedtime + timedelta(minutes=self.pauseondelay) <= now:
                    Domoticz.Debug("Pause is now On")
                    self.pause = True
                    self.switchHeat = False
                    Domoticz.Debug("TRV Calculded setpoint is : 7")
                    self.TRVsetpoint = 7
                    if not Devices[7].nValue == 0:
                        Devices[7].Update(nValue = 0,sValue = Devices[7].sValue)

            else: # thermostart is ok in auto mode

                self.switchHeat = True

                # make current setpoint used in calculation reflect the select mode (10= normal, 20 = economy)

                if Devices[2].sValue == "10":  # Mode Auto
                    if self.PresenceTH:
                        self.setpoint = float(Devices[4].sValue)
                        Domoticz.Log("AUTO Mode - used setpoint is NORMAL : " + str(self.setpoint))
                        self.TRVsetpoint = math.ceil(self.setpoint - (self.intemp - self.TRVtemp))   # correction of TRV setpoint using difference between real indoor temp and mesured trv temp.
                        Domoticz.Debug("TRV Calculded setpoint is : " + str(self.TRVsetpoint))

                    else:
                        self.setpoint = (float(Devices[4].sValue) - ((self.reducjour) / 10))
                        Domoticz.Log("AUTO Mode - used setpoint is reducted one : " + str(self.setpoint))
                        self.TRVsetpoint = math.ceil(self.setpoint - (self.intemp - self.TRVtemp))   # correction of TRV setpoint using difference between real indoor temp and mesured trv temp.
                        Domoticz.Debug("TRV Calculded setpoint is : " + str(self.TRVsetpoint))

                elif Devices[2].sValue == "20":  # Mode ECO
                    self.setpoint = float(Devices[5].sValue)
                    Domoticz.Log("ECO Mode - used setpoint is ECO one : " + str(self.setpoint))
                    self.TRVsetpoint = math.ceil(self.setpoint - (self.intemp - self.TRVtemp))   # correction of TRV setpoint using difference between real indoor temp and mesured trv temp.
                    Domoticz.Debug("TRV Calculded setpoint is : " + str(self.TRVsetpoint))

                else:
                    self.setpoint = 15  # Mode Vacances
                    Domoticz.Log("VACATION Mode - used setpoint is VACATION one : " + str(self.setpoint))
                    self.TRVsetpoint = math.ceil(self.setpoint - (self.intemp - self.TRVtemp))   # correction of TRV setpoint using difference between real indoor temp and mesured trv temp.
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


        if self.RefreshAndActTime + timedelta(seconds=self.NextInterval) <= now:
            # reset timer
            self.RefreshAndActTime = now
            # on redéfinit un nouvel intervalle pour le prochain tour
            self.NextInterval = random.randint(60, 90)
            Domoticz.Debug("Action déclenchée (prochain déclenchement dans {}s)".format(self.NextInterval))
            # refresh values and act
            self.PresenceDetection()
            # we update the TRV Setpoint
            self.TRVsetpoint = round(self.TRVsetpoint)  # on arrondi au setpoint sans virgule
            Domoticz.Log("TRV Calculded setpoint is : " + str(self.TRVsetpoint))
            # mise à jour uniquement si nécessaire
            # mise à jour des TRV uniquement si nécessaire
            for idx in self.Heaters:
                # Récupérer les infos du device TRV via l'API Domoticz
                deviceAPI = DomoticzAPI("type=command&param=getdevices&rid={}".format(idx))
                if (not deviceAPI) or ("result" not in deviceAPI) or (len(deviceAPI["result"]) == 0):
                    Domoticz.Error("Heater idx {} not found in Domoticz (API)".format(idx))
                    continue

                dev = deviceAPI["result"][0]

                # Selon le type, la consigne peut être dans SetPoint, Data ou sValue
                val_str = dev.get("SetPoint") or dev.get("Data") or dev.get("sValue")

                if val_str is None:
                    Domoticz.Error("Heater idx {} has no usable setpoint field in API result".format(idx))
                    continue
                try:
                    current_sp = float(val_str)
                except ValueError:
                    Domoticz.Error("Heater idx {} has invalid setpoint value: '{}'".format(idx, val_str))
                    continue

                # Comparaison avec tolérance pour éviter les micro-différences
                if abs(current_sp - self.TRVsetpoint) > 0.05:
                    Domoticz.Log("Update TRV idx {} from {} to {}".format(idx, current_sp, self.TRVsetpoint))
                    DomoticzAPI("type=command&param=setsetpoint&idx={}&setpoint={}".format(idx, self.TRVsetpoint))
                else:
                    Domoticz.Log("TRV idx {} already at setpoint {}, no update".format(idx, current_sp))

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
                devicesAPI = DomoticzAPI("type=command&param=getdevices&filter=light&used=true&order=Name")
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

    # Read Temperature  functions ---------------------------------------------------
    def readTemps(self):
        Domoticz.Debug("readTemps called")
        self.nexttemps = datetime.now()
        # fetch all the devices from the API and scan for sensors
        noerror = True
        listintemps = []
        listtrvtemps = []
        devicesAPI = DomoticzAPI("type=command&param=getdevices&filter=temp&used=true&order=Name")
        if devicesAPI:
            for device in devicesAPI["result"]:
                idx = int(device["idx"])
                # Room Temp
                if idx in self.InTempSensors:
                    # Ignorer temporairement s'il est dans la liste d'exclusion
                    if idx in self.TempExcludedUntil:
                        if datetime.now() < self.TempExcludedUntil[idx]:
                            Domoticz.Debug(
                                f"Capteur température idx {idx} temporairement exclu jusqu’à {self.TempExcludedUntil[idx]}")
                            continue
                        else:
                            del self.TempExcludedUntil[idx]  # Réintégrer après délai
                    # Vérifier le status du capteur
                    skip = False
                    if device.get("HardwareName") != "Dummies":
                        if device.get("HaveTimeout", False):
                            skip = True
                        else:
                            last_update_str = device.get("LastUpdate")
                            if last_update_str:
                                try:
                                    last_update = datetime.strptime(last_update_str, "%Y-%m-%d %H:%M:%S")
                                    if datetime.now() - last_update > timedelta(minutes=30):
                                        skip = True
                                except Exception as e:
                                    Domoticz.Error(f"Erreur de parsing LastUpdate pour capteur {device['Name']}: {e}")
                                    skip = True
                    if skip:
                        self.TempExcludedUntil[idx] = datetime.now() + timedelta(minutes=15)
                        Domoticz.Debug(
                            f"Exclusion température idx {idx} jusqu’à {self.TempExcludedUntil[idx]} pour timeout ou LastUpdate trop vieux")
                        Domoticz.Error("Device with idx '{}' named '{}' is TimedOut !".format(idx, device["Name"]))
                        continue
                    # Capteur valide
                    if "Temp" in device:
                        Domoticz.Debug("device: {}-{} = {}".format(device["idx"], device["Name"], device["Temp"]))
                        listintemps.append(device["Temp"])
                    else:
                        Domoticz.Error(
                            "device: {}-{} is not a Temperature sensor".format(device["idx"], device["Name"]))
                # TRV Temp
                elif idx in self.TRVTempSensors:
                    # Ignorer temporairement s'il est dans la liste d'exclusion
                    if idx in self.TempExcludedUntil:
                        if datetime.now() < self.TempExcludedUntil[idx]:
                            Domoticz.Debug(
                                f"Capteur température idx {idx} temporairement exclu jusqu’à {self.TempExcludedUntil[idx]}")
                            continue
                        else:
                            del self.TempExcludedUntil[idx]  # Réintégrer après délai
                    # Vérifier le status du capteur
                    skip = False
                    if device.get("HardwareName") != "Dummies":
                        if device.get("HaveTimeout", False):
                            skip = True
                        else:
                            last_update_str = device.get("LastUpdate")
                            if last_update_str:
                                try:
                                    last_update = datetime.strptime(last_update_str, "%Y-%m-%d %H:%M:%S")
                                    if datetime.now() - last_update > timedelta(minutes=30):
                                        skip = True
                                except Exception as e:
                                    Domoticz.Error(f"Erreur de parsing LastUpdate pour capteur {device['Name']}: {e}")
                                    skip = True
                    if skip:
                        self.TempExcludedUntil[idx] = datetime.now() + timedelta(minutes=15)
                        Domoticz.Debug(
                            f"Exclusion température idx {idx} jusqu’à {self.TempExcludedUntil[idx]} pour timeout ou LastUpdate trop vieux")
                        Domoticz.Error("Device with idx '{}' named '{}' is TimedOut !".format(idx, device["Name"]))
                        continue
                    # Capteur valide
                    if "Temp" in device:
                        Domoticz.Debug("device: {}-{} = {}".format(device["idx"], device["Name"], device["Temp"]))
                        listtrvtemps.append(device["Temp"])
                    else:
                        Domoticz.Error(
                            "device: {}-{} is not a TRV Temp sensor".format(device["idx"], device["Name"]))

        # calculate averages
        nb_in = len(listintemps)
        nb_trv = len(listtrvtemps)

        # --- 1) Inside temperature OK ---
        if nb_in > 0:
            self.intemp = round(sum(listintemps) / nb_in, 1)
            Devices[6].Update(nValue=0, sValue=str(self.intemp), TimedOut=False)

            if self.intemperror:
                # On sort du mode erreur si on en avait un
                self.intemperror = False
                self.WriteLog("Inside Temperature reading is now valid again: Resuming normal operation", "Status")
                Devices[1].Update(nValue=Devices[1].nValue, sValue=Devices[1].sValue, TimedOut=False)

            noerror = True

        # --- 2) Mode dégradé : pas de sonde intérieure, mais TRV OK ---
        elif nb_trv > 0:
            # On prend la moyenne des TRV comme température intérieure de secours
            self.intemp = round(sum(listtrvtemps) / nb_trv, 1)
            Devices[6].Update(nValue=0, sValue=str(self.intemp), TimedOut=False)

            if self.intemperror:
                # Si on était en erreur avant, on repasse en mode "dégradé mais actif"
                self.intemperror = False
                Devices[1].Update(nValue=Devices[1].nValue, sValue=Devices[1].sValue, TimedOut=False)

            Domoticz.Error("No valid Inside Temperature found: using TRV temperatures in degraded mode.")
            noerror = True  # On autorise le chauffage à continuer sur cette base

        # --- 3) Erreur totale : ni Inside ni TRV ---
        else:
            Domoticz.Error("No Inside Temperature and no TRV Temperature available... ")
            if not self.intemperror:
                self.intemperror = True
                Domoticz.Error("Switching heating request Off (no temperature reference).")
                self.switchHeat = False
                Devices[1].Update(nValue=Devices[1].nValue, sValue=Devices[1].sValue, TimedOut=True)
                Devices[6].Update(nValue=Devices[6].nValue, sValue=Devices[6].sValue, TimedOut=True)
            return False  # pas de référence de température exploitable

        # --- TRV temperature calculation ---
        if nb_trv > 0:
            self.TRVtemp = round(sum(listtrvtemps) / nb_trv, 1)
        else:
            # Pas de TRV dispo : on se rabat sur intemp si elle existe,
            # sinon valeur neutre (mais le cas "plus rien du tout" est déjà géré plus haut)
            Domoticz.Debug("No TRV Temperature found... Using Inside temperature as TRV temp")
            self.TRVtemp = self.intemp

        self.WriteLog("Inside Temperature = {}".format(self.intemp), "Verbose")
        self.WriteLog("TRV Temperature = {}".format(self.TRVtemp), "Verbose")
        return noerror


    # WriteLog functions ---------------------------------------------------

    def WriteLog(self, message, level="Normal"):

        if self.loglevel == "Verbose" and level == "Verbose":
            Domoticz.Log(message)
        elif level == "Normal":
            Domoticz.Log(message)


# Plugin functions ---------------------------------------------------

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
        value = value.strip()
        if value == "":
            continue
        try:
            val = int(value)
            listvals.append(val)
        except ValueError:
            try:
                val = float(value)
                listvals.append(val)
            except ValueError:
                Domoticz.Error(f"Skipping non-numeric value: '{value}'")
    return listvals



def DomoticzAPI(APICall):
    resultJson = None
    url = f"http://127.0.0.1:8080/json.htm?{parse.quote(APICall, safe='&=')}"

    try:
        Domoticz.Debug(f"Domoticz API request: {url}")
        req = request.Request(url)
        response = request.urlopen(req)

        if response.status == 200:
            resultJson = json.loads(response.read().decode('utf-8'))
            if resultJson.get("status") != "OK":
                Domoticz.Error(f"Domoticz API returned an error: status = {resultJson.get('status')}")
                resultJson = None
        else:
            Domoticz.Error(f"Domoticz API: HTTP error = {response.status}")


    except urlerror.HTTPError as e:
        Domoticz.Error(f"HTTP error calling '{url}': {e}")

    except urlerror.URLError as e:
        Domoticz.Error(f"URL error calling '{url}': {e}")

    except json.JSONDecodeError as e:
        Domoticz.Error(f"JSON decoding error: {e}")

    except Exception as e:
        Domoticz.Error(f"Error calling '{url}': {e}")

    return resultJson



def CheckParam(name, value, default):
    try:
        param = int(value)
    except ValueError:
        param = default
        Domoticz.Error( f"Parameter '{name}' has an invalid value of '{value}' ! defaut of '{param}' is instead used.")
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


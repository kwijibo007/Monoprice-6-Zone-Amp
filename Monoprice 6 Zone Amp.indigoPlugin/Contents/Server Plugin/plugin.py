#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
# Copyright (c) 2015, Peter Dowles
# https://aushomeautomator.wordpress.com/monoprice-6-zone-amp-indigo-plugin/


import indigo
import serial
import time
import Queue
import thread
import datetime
import logging

xPA = 1
xPR = 2
xMU = 3
xDT = 4
xVO = 5
xTR = 6
xBS = 7
xBL = 8
xCH = 9
xKP = 10

override = False

lastChange = datetime.datetime.now()
lastMultiChange = datetime.datetime.now()
multiCMD = ""

#Declare global variables
ser = serial
q = Queue.Queue()#maxsize=5)
serialUIAddress = None

stallingSafeGuard = 0


################################################################################
class Plugin(indigo.PluginBase):
    ########################################
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        #self.debug = True

        # Configure logging
        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s',
                                 datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)

        try:
            self.logLevel = int(self.pluginPrefs[u"logLevel"])
        except:
            self.logLevel = logging.INFO
        self.indigo_log_handler.setLevel(self.logLevel)
        self.logger.debug(u"logLevel = " + str(self.logLevel))


    ########################################
    def startup(self):

        self.logger.debug(u"Startup Called")

        global ser, serialUIAddress

        serialUrl = self.getSerialPortUrl(self.pluginPrefs, u"rs2322")
        serialUIAddress = serialUrl

        try:
            if ser is None:
                pass
            else:
                ser.close()
        except:
            #self.debugLog("Fail because conn does not yet exist.")
            self.logger.debug("Serial port is not open (Could be an error - ignore if the plugin is starting)")

        self.portEnabled = False
        try:
            self.logger.debug("Serial Port URL is " + serialUrl)
            ser = self.openSerial(u"Monoprice 6 Zone Amp", serialUrl, 9600, timeout=1, )
        except:
            self.logger.critical("Getting and setting the serial port caused error.")


        if ser is not None:
            self.logger.debug("Success! Serial Port Open.")
            self.portEnabled = True
        else:
            self.logger.critical("Unable to open serial port.")
            self.logger.critical("Check serial port and plugin configuration. Then restart the plugin.")


    ########################################
    def shutdown(self):
        # close serial port here
        self.logger.debug("Shutdown Called")
        ser.close()
        
    ########################################
    def __del__(self):
        indigo.PluginBase.__del__(self)

    ########################################
    def runConcurrentThread(self):
        thread.start_new_thread(self.queueWorker, ())
        thread.start_new_thread(self.volumeWatcher, ())
        try:
            while True:
            
                self.logger.debug("The size of the queue is: " + str(q.qsize()))
                for qObj in q.queue:
                    self.logger.debug(str(qObj))
                if q.qsize() == 0:
                    q.put("?10")
                    self.logger.debug("q size = " + str(q.qsize()))
                    
                    stallingSafeGuard = 0
                
                self.logger.debug("runConcurrentThread - while True")
                
                self.logger.debug("Stalling Safe Guard Count: " + str(stallingSafeGuard))
                stallingSafeGuard = stallingSafeGuard + 1
                if stallingSafeGuard > 30:
                    self.logger.error("Stalling detected - Restarting plugin")
                    plugin = indigo.server.getPlugin("net.dowles.monoprice6zoneamp")
                    if plugin.isEnabled():
                        plugin.restart()

                
                self.sleep(2)
        except self.StopThread: 
            self.logger.error("An error occurred adding a polling command to the queue")
        
    
    ########################################
    def pollAmp(self,response):
        self.logger.debug("*#* Var: response: " + str(response))
        settings = [] 

        lines = response.split('\n')
    
        #Iterate through response and sepearte zones into a list of arrays
        for line in lines[1:-1]:
            settings.append(map(''.join, zip(*[iter(line[2:].replace("\r",""))]*2)))
        
        for dev in indigo.devices.iter("self"):
            zone = (int(dev.pluginProps["zoneID"]) - 11)

            self.logger.debug("*#* Var: Settings: " + str(settings))
            if len(settings) == 6:

                if dev.enabled or dev.configured:
                    #Need to block status updates that snuck in just before the change
                    dateDiff = (datetime.datetime.now() - lastChange).seconds

                    if dateDiff > 2:
                        ###Power###
                        if str(settings[zone][xPR]) == "01":
                            state = "On"
                        else:
                            state = "Off"

                        if settings[zone][xMU] == "00":
                            muteState = "Off"
                        else:
                            muteState = "On"

                        #!!What happens if source has no name????????
                        sourceName = self.pluginPrefs["source" + settings[zone][xCH][1:]]

                        keyValueList = [
                            {'key': 'onOffState', 'value': state},
                            {'key': 'source', 'value': sourceName},
                            {'key': 'mute', 'value': muteState},
                            {'key': 'volume', 'value': settings[zone][xVO]},
                            {'key': 'balance', 'value': settings[zone][xBL]},
                            {'key': 'bass', 'value': settings[zone][xBS]},
                            {'key': 'treble', 'value': settings[zone][xTR]}
                        ]
                        dev.updateStatesOnServer(keyValueList)  ###Update device states###
            else:
                self.logger.error("More than 6 zones have been returned - Should not be possible??")
    ########################################
    def queueWorker(self):
        self.logger.debug("Queue worker starting")
        while True:

            strCMD = q.get()
            self.logger.debug("*#* Var: strCMD: " + str(strCMD))
            try:
                ser.flush
                ser.write(strCMD + "\x0d") # write command
            except:
                self.logger.error("Unable to connect to Amp. Command: " + strCMD)

            time.sleep(0.1)
            response = ser.read(200)

            q.task_done()

            if strCMD == "?10":
                 self.pollAmp(response)
                 
    
    

    ########################################
    def volumeWatcher(self):
        multiCMDCompare = ""
        while True:
            dateDiff = (datetime.datetime.now() - lastMultiChange).microseconds
            if dateDiff > 500000:
                if multiCMD != multiCMDCompare:
                    q.put(multiCMD)
                    multiCMDCompare = multiCMD
            time.sleep(0.1)

    ########################################
    def validatePrefsConfigUi(self, valuesDict):

        errorDict = indigo.Dict()

        self.validateSerialPortUi(valuesDict, errorDict, u"rs2322")

        #Validate that the 6 source name fields are not blank if they're enabled
        for i in range(6):
            if valuesDict["enableSource" + str(i+1)] == True:
                if not valuesDict["source" + str(i+1)]:
                    errorDict["source" + str(i+1)] = "Source name must not be blank"

        if len(errorDict) > 0:
            return (False, valuesDict, errorDict)
        else:
            return (True, valuesDict)

    ########################################
    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        self.debugLog("closedPrefsConfigUI() called")
        if userCancelled:
            pass
        else:
            global serialUIAddress
            if serialUIAddress != valuesDict["rs2322_uiAddress"]:
                self.startup()

            #Configure logging
            try:
                self.logLevel = int(valuesDict[u"logLevel"])
            except:
                self.logLevel = logging.INFO
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(u"logLevel = " + str(self.logLevel))




    ########################################
    def validateActionConfigUi(self, valuesDict, typeId, devId):
        return (True, valuesDict)
	
	########################################
    def actionControlDimmerRelay(self, action, dev):
    ###### TURN ON ######
        if action.deviceAction == indigo.kDeviceAction.TurnOn:
            self.logger.debug(dev.name + " - Power: Turn on")
            self.zonePower(1,"On",dev)
    ###### TURN OFF ######            
        if action.deviceAction == indigo.kDeviceAction.TurnOff:
            self.logger.debug(dev.name + " - Power: Turn off")
            self.zonePower(0,"Off",dev)
    ###### Toggle ###### 
        if action.deviceAction == indigo.kDeviceAction.Toggle:
            if dev.onState == True:
                self.logger.debug(dev.name + " - Power: Turn off (toggle)")
                self.zonePower(0,"Off",dev)
            elif dev.onState == False:
                self.logger.debug(dev.name + " - Power: Turn on (toggle)")
                self.zonePower(1,"On",dev)
            else:	        
                self.logger.error(dev.name + " - Power in inconsistent state")


    ########################################
    def zonePower(self,binState,state,dev):
        self.logger.info(dev.name + " - Power " + state)
        global lastChange
        lastChange = datetime.datetime.now()
        zone = dev.pluginProps["zoneID"]
        dev.updateStateOnServer("onOffState", state)
        q.put("<" + str(zone) + "PR0" + str(binState))


    ########################################
    def actionControlMulti(self, action, dev):

        actionID = action.pluginTypeId
        actionType = actionID[:3]

        self.logger.debug(dev.name + " - " + actionID)

        if "Volume" in actionID:
            type = "volume"
            maxValue = int(dev.pluginProps["maxVol"])
            minValue = 0
            cmdCode = "VO"
        elif "Bass" in actionID:
            type = "bass"
            maxValue = 14
            minValue = 0
            cmdCode = "BS"
        elif "Balance" in actionID:
            type = "balance"
            maxValue = 20
            minValue = 0
            cmdCode = "BL"
        elif "Treble" in actionID:
            type = "treble"
            maxValue = 14
            minValue = 0
            cmdCode = "TR"
        else:
            self.logger.error("Unknown action type")
            return

        if dev.onState == False:
            self.logger.debug(dev.name + " - Unable to set " + type + ". The zone is turned off.")
            return

        currentValue = dev.states[type]
        strValue = currentValue

        ###### Set Exact Value ######
        if actionType == "set":
            strValue = action.props[type]

        ###### Increment ######
        if actionType == "inc":
            strValue = str(int(currentValue) + 1)

        ###### Decrement ######
        if actionType == "dec":
            strValue = str(int(currentValue) - 1)

        # Value out of range
        if (int(strValue) > maxValue or int(strValue) < minValue):
            self.logger.info(dev.name + " - " + type.capitalize() + ": Out of range - Tried:" + strValue + " Max:" + str(maxValue) + " Min:" + str(minValue))
            return

        # Value out of range (SAFETY). Icase the actual volume is some how out of range
        if (int(currentValue) > maxValue or int(currentValue) < minValue):
            self.logger.error(dev.name + " - " + type.capitalize() + ": Out of range - Max:" + str(maxValue) + " Min:" + str(minValue))
            strValue = "0"

        # Set value
        if len(strValue) == 1:
            strValue = "0" + strValue
        global lastChange
        lastChange = datetime.datetime.now()

        zone = dev.pluginProps["zoneID"]
        dev.updateStateOnServer(type, strValue)

        global lastMultiChange
        # Variables used by the multiWatcher method to support smoother changes when comming on the back of earch other
        lastMultiChange = datetime.datetime.now()
        global multiCMD
        multiCMD = "<" + str(zone) + cmdCode + strValue
        self.logger.info(dev.name + " - " + type.capitalize() + " " + "set: " + strValue)



    
    ########################################    
    def actionControlSource(self,action,dev):

        if dev.onState == False:
            self.logger.debug(dev.name + " - Unable to set source. The zone is turned off.")
            return

        actionID = action.pluginTypeId
        currentLbl = dev.states["source"]

        #Create list of enabled sources and determine the current source number
        currentSource = None
        sourceList = list()
        x = 0
        for i in range(6):
            if self.pluginPrefs["enableSource" + str(i + 1)] == True:
                sourceName = self.pluginPrefs["source" + str(i + 1)]
                sourceNumber = str(i + 1)
                sourceList.append(sourceNumber)
                if currentLbl == sourceName:
                    currentSource = sourceNumber
                    sourceIndex = x
                x=x+1

        #Exit if no sources are enabled
        if not sourceList:
            self.logger.warning("No sources are enabled. See plugin configuration to enable.")
            return

        ###### Set Source ######
        if actionID == "setSource":
            strSource = action.props["source"]
        ###### Toggle Source Fwd ######
        elif actionID == "toggleSourceFwd":
            if currentSource is None:
                strSource = str(sourceList[0])
            elif (sourceIndex+2) > len(sourceList):
                strSource = sourceList[0]
            else:
                strSource = sourceList[sourceIndex+1]
        ###### Toggle Source Rev ######
        elif actionID == "toggleSourceRev":
            if currentSource is None:
                str(sourceList[0])
            elif sourceIndex == 0:
                strSource = str(sourceList[len(sourceList)-1])
            else:
                strSource = sourceList[sourceIndex - 1]
        else:
            self.logger.error(dev.name + " - Unknown source action (" + actionID + ")")
            return


        strSourceLbl = self.pluginPrefs["source" + strSource]
        #Set source
        if self.pluginPrefs["enableSource" + strSource] == True:
            global lastChange
            lastChange = datetime.datetime.now()
            zone = dev.pluginProps["zoneID"]
            dev.updateStateOnServer("source", strSourceLbl)
            q.put("<" + str(zone) + "CH" + str(int(strSource)+10))
            self.logger.info(dev.name + " - Source set: " + strSourceLbl)
        else:
            if not self.pluginPrefs["source" + strSource]:
                strSourceMsg = "Source " + strSource
            else:
                strSourceMsg = "Source " + strSourceLbl + " (Source " + strSource + ")"
            self.logger.warning(strSourceMsg + " is disabled. See plugin configuration to enable.")

    

    ########################################    
    def actionControlMute(self,action,dev):

        if dev.onState == False:
            self.logger.debug(dev.name + " - Unable to set mute. The zone is turned off.")
            return
        
        actionID = action.pluginTypeId
        
        ###### Mute On ######
        if actionID == "onMute":
            self.logger.debug(dev.name + " - Mute: Turn on")
            muteMode = "01"
            muteState ="On"
        ###### Mute Off ######
        if actionID == "offMute":
            self.logger.debug(dev.name + " - Mute: Turn off")
            muteMode = "00"
            muteState ="Off"
        ###### Toggle Mute ######
        if actionID == "toggleMute":
            if dev.states["mute"] == "On":
                self.logger.debug(dev.name + " - Mute: Turn off (toggle)")
                muteMode = "00"
                muteState ="Off"
            else:
                self.logger.debug(dev.name + " - Mute: Turn on (toggle)")
                muteMode = "01"
                muteState ="On" 
        
        
        global lastChange 
        lastChange = datetime.datetime.now()
        zone = dev.pluginProps["zoneID"]
        self.logger.info(dev.name + " - Mute " + muteState)
        dev.updateStateOnServer("mute", muteState)
        q.put("<" + str(zone) + "MU" + muteMode)

    ########################################
    def sourceListGenerator(self, filter="", valuesDict=None, typeId="", targetId=0):
        #Iterate through all the sources and add them to the list if they're enabled
        sourceList = list()
        for i in range(6):
            if self.pluginPrefs["enableSource" + str(i+1)] == True:
                sourceList.append((str(i+1),self.pluginPrefs["source" + str(i+1)]))
        return sourceList

        
	########################################
	def actionControlGeneral(self, action, dev):
	#General Action callback
		###### BEEP ######
		if action.deviceAction == indigo.kDeviceGeneralAction.Beep:
			# Beep the hardware module (dev) here:
			# ** IMPLEMENT ME **
			indigo.server.log(u"sent \"%s\" %s" % (dev.name, "beep request"))

		###### ENERGY UPDATE ######
		elif action.deviceAction == indigo.kDeviceGeneralAction.EnergyUpdate:
			# Request hardware module (dev) for its most recent meter data here:
			# ** IMPLEMENT ME **
			indigo.server.log(u"sent \"%s\" %s" % (dev.name, "energy update request"))

		###### ENERGY RESET ######
		elif action.deviceAction == indigo.kDeviceGeneralAction.EnergyReset:
			# Request that the hardware module (dev) reset its accumulative energy usage data here:
			# ** IMPLEMENT ME **
			indigo.server.log(u"sent \"%s\" %s" % (dev.name, "energy reset request"))

		###### STATUS REQUEST ######
		elif action.deviceAction == indigo.kDeviceGeneralAction.RequestStatus:
			# Query hardware module (dev) for its current status here:
			# ** IMPLEMENT ME **
			indigo.server.log(u"sent \"%s\" %s" % (dev.name, "status request"))
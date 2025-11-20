# SmartVirtualThermostat for TRV
Smart Virtual Thermostat python plugin for Domoticz home automation system

install :

cd ~/domoticz/plugins 

git clone https://github.com/Erwanweb/SVT3.git SVT3

cd SVT3

sudo chmod +x plugin.py

sudo /etc/init.d/domoticz.sh restart

Upgrade :

cd ~/domoticz/plugins/SVT3

git reset --hard && git pull --force

sudo /etc/init.d/domoticz.sh restart



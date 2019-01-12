# SmartVirtualThermostat for TRV
Smart Virtual Thermostat python plugin for Domoticz home automation system

install :

cd ~/domoticz/plugins 

mkdir SVT3

sudo apt-get update

sudo apt-get install git

git clone https://github.com/Erwanweb/SVT2.git SVT2

cd SVT3

sudo chmod +x plugin.py

sudo /etc/init.d/domoticz.sh restart

Upgrade :

cd ~/domoticz/plugins/SVT3

git reset --hard

git pull --force

sudo chmod +x plugin.py

sudo /etc/init.d/domoticz.sh restart



<a href="https://www.buymeacoffee.com/IntExCZ" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee" height="41" width="174"></a>

# Toshiba-HVAC
Toshiba HVAC ESP8266 control based on Tasmota firmware with external API (PHP/Python).  
For Toshiba Shorai-Edge compatible units.

Home Assistant integration based on AppDaemon Python/MQTT control script.

I will add instructions, but if someone interested can help me, I will appreciate it. ;-)

![Installation](/images/installation.jpg)  
(Final installation of ESP in the unit)  

![ESP-01](/HomeAssistant/Lovelace_example.png)  
(Example of Home Assistnant's Lovelace component)  

## Used software components
<a href="https://tasmota.github.io/" target="_blank">Tasmota Firmware</a>  
<a href="https://www.home-assistant.io/" target="_blank">Home Assistant</a>  
<a href="https://appdaemon.readthedocs.io/" target="_blank">AppDaemon for Home Assistant</a>  

## Used hardware components
### ESP-01
![ESP-01](/images/esp01.jpg)  

### ESP-01 Serial Adapter
![ESP-01](/images/esp01_adapter.jpg)  

## HVAC cable connection
**BLUE** = to ESP TX  
**PINK** = GND  
**BLACK** = +5V VCC  
**WHITE** = to ESP RX

## Tasmota configuration
Flash Tasmota to ESP, set password and WiFi network parameters.    
  
In console input these commands:  

`SerialConfig 8E1`  

`Baudrate 9600`  

`Rule1 ON Time#Minute DO SerialSend5 020003100000060130010001BBF9 ENDON`  

`Rule1 1`  

`Rule2 ON SerialReceived#Data$<0200039000000901300100000002 DO Var2 %value% ENDON ON SerialReceived#Data$<0200039000000801300100000001 DO Var3 %value% ENDON`  

`Rule2 1`  

`Rule3 ON Wifi#Connected DO Backlog SerialConfig 8O1; SerialConfig 8E1; Delay 10; SerialSend5 02FFFF0000000002; SerialSend5 02FFFF0100000102FE; SerialSend5 020000000000020202FA; SerialSend5 0200018101000200007B; SerialSend5 020001020000020000FB; SerialSend5 02000200000000FE; Delay 20; SerialSend5 020002010000020000FB; SerialSend5 020002020000020000FA ENDON`  

`Rule3 1`  

(It is the serial configuration, keep-alive timer, HVAC response extraction and WiFi reconnection handshake.)    
  
Nothing else need to be set.

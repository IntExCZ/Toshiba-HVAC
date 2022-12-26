import re # regular expressions
import urllib.request
import time
import json

debug = False

# Tasmota parametes
tasmota_host = '192.168.1.101'
tasmota_username = 'admin'
tasmota_password = '12345'

## Function constants (decimal) ##
function_codes = {}
function_codes['TEMP_SETPOINT']  = '179' # 17-32 degrees
function_codes['TEMP_INDOOR']  = '187'
function_codes['TEMP_OUTDOOR'] = '190'
function_codes['POWER_STATE']  = '128'
function_codes['POWER_SEL']    = '135' # 50/75/100
function_codes['TIMER_ON']     = '144'
function_codes['TIMER_OFF']    = '148'
function_codes['FAN_MODE']     = '160'
function_codes['SWING_STATE']  = '163'
function_codes['UNIT_MODE']    = '176'
function_codes['SPECIAL_MODE'] = '247'

function_values = {}
function_values['POWER_STATE']  = {'0':'-', '48':'ON', '49':'OFF'}
function_values['FAN_MODE']     = {'0':'-', '49':'QUIET', '50':'1', '51':'2', '52':'3', '53':'4', '54':'5', '65':'AUTO'}
function_values['SWING_STATE']  = {'0':'-', '49':'OFF', '65':'ON'}
function_values['UNIT_MODE']    = {'0':'-', '65':'AUTO', '66':'COOL', '67':'HEAT', '68':'DRY', '69':'FAN'}
function_values['POWER_SEL']    = {'50':'50%', '75':'75%', '100':'100%'}
function_values['SPECIAL_MODE'] = {'0':'-', '1':'HIPOWER', '3':'ECO/CFTSLP', '4':'8C', '2':'SILENT-1', '10':'SILENT-2', '32':'FRPL1', '48':'FRPL2'}
function_values['TIMER_ON']     = {'65':'ON', '66':'OFF'}
function_values['TIMER_OFF']    = {'65':'ON', '66':'OFF'}

# Debug output message
# returns: none (output to stdout)
def debug_out(message = "", force = False): 
    if (not debug and not force):
        return
    print(message + "\n")

# Convert decimal string to HEX string
# returns: ex. '240' decimal converted to 'F0' HEX
def decstr_to_hexstr(input):
    result = str(hex(int(input))).replace('0x', '').upper()
    return result

# Send command to Tasmota
# returns: Tasmota response
def tasmota_send(command): 
    tasmota_command = "http://" + tasmota_host + "/cm?user=" + tasmota_username + "&password=" + tasmota_password + "&cmnd="
    if isinstance(command, list):
        command = 'BackLog ' + '; '.join(command) # convert to one line Backlog
    tasmota_command += urllib.parse.quote_plus(command) 
    debug_out(tasmota_command)
    result = urllib.request.urlopen(tasmota_command).read()
    #result = '{"Var2":"02000390000008013001000000018017"}'
    result = str(result).replace("b'{", "{").replace("}'", "}")
    debug_out(result)
    debug_out()
    return result

# Setup environment parameters in Tasmota
# returns: none
def tasmota_setup():
    # serial port parameters
    tasmota_send('SerialConfig 8E1')
    tasmota_send('Baudrate 9600')
    # keep-alive polling (indoor temperature query every minute)
    tasmota_send('Rule1 ON Time#Minute DO SerialSend5 020003100000060130010001BBF9 ENDON')
    tasmota_send('Rule1 1')
    # query/command response variables updating (store query response in Var2, store command response in Var3)
    tasmota_send('Rule2 ON SerialReceived#Data$<0200039000000901300100000002 DO Var2 %value% ENDON ON SerialReceived#Data$<0200039000000801300100000001 DO Var3 %value% ENDON')
    tasmota_send('Rule2 1')
    # AC init (handshake + aftershake) on WiFi connected (SerialConfig = Wemos D1 Mini Pro restart workaround)
    tasmota_send('Rule3 ON Wifi#Connected DO Backlog SerialConfig 8O1; SerialConfig 8E1; Delay 10; SerialSend5 02FFFF0000000002; SerialSend5 02FFFF0100000102FE; SerialSend5 020000000000020202FA; SerialSend5 0200018101000200007B; SerialSend5 020001020000020000FB; SerialSend5 02000200000000FE; Delay 20; SerialSend5 020002010000020000FB; SerialSend5 020002020000020000FA ENDON')
    tasmota_send('Rule3 1')

# Convert received temperature from AC (to positive/negative value)
# returns: signed decimal value
def convert_temperature(input_temperature):
    if (input_temperature == 127):
        return '-' # invalid value
    if (input_temperature > 127):
        return input_temperature - 256 # negative value
    return input_temperature # positive value

# Calculate checksum for HEX string command
# returns: string HEX checksum (ex. 'F0')
def ac_checksum(input_command):
    command_list = re.findall('..', input_command) # split into list by regex
    del command_list[0] # remove start byte (02)
    int_array = []
    for val in command_list:
        int_array.append(int(val, 16))
    checksum = (0x100-(sum(int_array)%0x100))%0x100 # Pajtnovej fujtajbl
    checksum = str(hex(checksum)).replace('0x', '').upper()
    if (len(checksum) < 2):
        checksum = '0' + checksum # leading zero
    debug_out("Checksum for command '" + input_command + "' is: " + checksum)
    return checksum

# Send Handshake + aftershake to AC
# returns: none
def ac_init():
    command = []
    command.append('SerialSend5 02FFFF0000000002')
    command.append('SerialSend5 02FFFF0100000102FE')
    command.append('SerialSend5 020000000000020202FA')
    command.append('SerialSend5 0200018101000200007B')
    command.append('SerialSend5 020001020000020000FB')
    command.append('SerialSend5 02000200000000FE')
    command.append('Delay 20')
    command.append('SerialSend5 020002010000020000FB')
    command.append('SerialSend5 020002020000020000FA')
    tasmota_send(command)
    time.sleep(2)
 
# Send command to AC (with result check+retry)
# example: ac_command('POWER_STATE', 'ON');
# returns: true/false (command success/fail)
ac_command_retries = [] # command retries log
def ac_command(input_function, input_value, num_retries = 4, retry_counter = 0, response_only = False):
    control_command_prefix = '020003100000070130010002'
    command_result_variable = 'Var3'
    if (not response_only): 
        if (input_function == 'SPECIAL_MODE' and ('SILENT' in input_value)):
            ac_command('POWER_SEL', '100%', num_retries, retry_counter); # set maximum power in silent mode (same as over IR)
        # prepare command
        control_command = control_command_prefix
        control_command += decstr_to_hexstr(function_codes[input_function]) # function code
        if (input_function != 'TEMP_SETPOINT'):
            input_value = list(function_values[input_function].keys())[list(function_values[input_function].values()).index(input_value)]
        control_command += decstr_to_hexstr(input_value) # value
        control_command += ac_checksum(control_command)
        # send command
        command = []
        command.append(command_result_variable + " " + input_function) # clear command result variable (set function code for console debug)
        command.append('SerialSend5 ' + control_command) # // query command (prefix + query code + checksum)
        tasmota_send(command)
    time.sleep(0.5) # time for AC response (500 ms)
    # get response
    response = tasmota_send(command_result_variable) # get query result variable
    response = json.loads(response) # convert to JSON object {"Var2":"02000390000008013001000000018017"}
    response = response[command_result_variable] # get query variable value
    # check response
    command_response_prefix = '0200039000000801300100000001'
    command_response_prefix += decstr_to_hexstr(function_codes[input_function]) # prefix + query code
    valid_response = command_response_prefix in response
    if (not valid_response):
        if (retry_counter == num_retries):
            return False # no more retries
        retry_counter += 1
        ac_command_retries.append(input_function + ": " + str(retry_counter) + ". retry")
        return ac_command(input_function, input_value, num_retries, retry_counter, retry_counter%2 == 1) # even retry = retry whole command, odd retry = re-read response
    return True

# Query AC state (with result check+retry)
# returns: decimal temperature/translated value/
ac_query_retries = []; # query retries log
ac_state_valid = True # query validity flag (if all states were retrieived)
def ac_query(input_function, num_retries = 4, retry_counter = 0, response_only = False):
    query_command_prefix = '020003100000060130010001'
    query_result_variable = 'Var2'
    if (not response_only):
        # prepare query
        query_command = query_command_prefix
        query_command += decstr_to_hexstr(function_codes[input_function]) # ex. 020003100000060130010001+BB (room temp)
        query_command += ac_checksum(query_command) # ex. 020003100000060130010001BB+F9 (checksum)
        # send query
        command = []
        command.append(query_result_variable + " " + input_function) # clear query result variable 
        command.append('SerialSend5 ' + query_command) # query command (prefix + query code + checksum)
        tasmota_send(command)
    time.sleep(0.5) # time for AC response (500 ms)
    # get response
    response = tasmota_send(query_result_variable) # get query result variable
    response = json.loads(response) # convert to JSON object {"Var2":"0200039000000901300100000002BB17"}
    response = response[query_result_variable] # get query variable value
    # check response
    query_response_prefix = '0200039000000901300100000002'
    query_response_prefix += decstr_to_hexstr(function_codes[input_function]) # prefix + query code
    valid_response = query_response_prefix in response
    if (not valid_response):
        if (retry_counter == num_retries):
            ac_state_valid = False
            return False; # no more retries
        retry_counter += 1
        ac_query_retries.append(input_function + ": " + str(retry_counter) + ". retry")
        return ac_query(input_function, num_retries, retry_counter, retry_counter%2 == 1) # even retry = retry whole query, odd retry = re-read response
    # parse response
    result = response.replace(query_response_prefix, '')[0:2] # value is 2 chars after prefix
    result = int(result, 16) # convert HEX to decimal
    if ('TEMP_' in input_function):
        return convert_temperature(result) # temperature value
    result = str(result)
    if (input_function in function_values):
        return function_values[input_function][result] # translate if known
    return result; # decimal value

## MAIN BODY ##
for key in function_codes:
    print(key + ": " + str(ac_query(key)))
#print(str(ac_query('TEMP_SETPOINT')))   
print(str(ac_command('POWER_STATE', 'OFF')))

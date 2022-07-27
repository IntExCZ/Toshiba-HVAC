import mqttapi as mqtt
import adbase as ad
import json
import datetime
import re # regular expressions
import urllib.request
import time
import unicodedata

class Toshiba_HVAC(mqtt.Mqtt):

  # runtime variables
  topic_group = "toshiba-hvac"
  topic_prefix = None # toshiba-hvac/pracovna
  tasmota_username = "admin"

  callback_lock = False # avoid callback locking to avoid concurrent runnings
  is_connected = None # connection state reported by tasmota_send()

  # configuration values
  room_name = None
  tasmota_host = None
  tasmota_password = None
  set_log = False
  debug_log = False
  hvac_log = False
  tasmota_log = False
  full_polling_sec = None
  temps_polling_sec = None

  # States for HA
  states = {'POWER_STATE', 'UNIT_MODE', 'POWER_SEL', 'SPECIAL_MODE', 'FAN_MODE', 'SWING_STATE', 'TEMP_PRESET', 'TEMP_INDOOR', 'TEMP_OUTDOOR'}
  
  # HVAC function codes (decimal)
  function_codes = {
    'TEMP_PRESET':  '179', # 17-32 degrees
    'TEMP_INDOOR':  '187',
    'TEMP_OUTDOOR': '190',
    'POWER_STATE':  '128',
    'POWER_SEL':    '135', # 50/75/100
    'TIMER_ON':     '144',
    'TIMER_OFF':    '148',
    'FAN_MODE':     '160',
    'SWING_STATE':  '163',
    'UNIT_MODE':    '176',
    'SPECIAL_MODE': '247'
  }
  
  # HVAC function possible values
  function_values = {
    'POWER_STATE':  {'0':'-', '48':'ON', '49':'OFF'},
    'FAN_MODE':     {'0':'-', '49':'QUIET', '50':'1', '51':'2', '52':'3', '53':'4', '54':'5', '65':'AUTO'},
    'SWING_STATE':  {'0':'-', '49':'off', '65':'on'}, # adapted to HA states
    'UNIT_MODE':    {'0':'-', '65':'auto', '66':'cool', '67':'heat', '68':'dry', '69':'fan_only'}, # adapted to HA states
    'POWER_SEL':    {'50':'50', '75':'75', '100':'100'}, # adapted to HA states
    'SPECIAL_MODE': {'0':'-', '1':'HIPOWER', '3':'ECO/CFTSLP', '4':'8C', '2':'SILENT1', '10':'SILENT2', '32':'FRPL1', '48':'FRPL2'},
    'TIMER_ON':     {'65':'ON', '66':'OFF'},
    'TIMER_OFF':    {'65':'ON', '66':'OFF'}
  }


# === MQTT FUNCTIONS ===
  
  def discovery_create_control(self, type, name, config):
    self.log_debug(f"discovery_create_control('{type}', '{name}', config)")
    config = json.dumps(config)
    topic = f"homeassistant/{type}/{name}/config"
    self.mqtt_publish(topic, config, qos=1, namespace="mqtt")
  
  # Create config for HA discovery mechanism
  def discovery_config(self):
    self.log_debug(f"set_discovery_config()")
    unique_name = self.normalize_string(f"{self.room_name}-hvac")
    # Climate device
    config = {
      "name": self.room_name,
      "unique_id": unique_name,
      "device": {
        "name": f"{self.room_name} HVAC",
        "identifiers": unique_name,
        "manufacturer": "Tasmota",
        "model": "Toshiba",
        "configuration_url": f"http://{self.tasmota_host}"
      },
      "icon": "mdi:hvac",
      "min_temp": "17",
      "max_temp": "32",
      "fan_modes": ["QUIET", "1", "2", "3", "4", "5","AUTO"],
      "availability_topic": f"{self.topic_prefix}/connection_state",
      "power_command_topic": f"{self.topic_prefix}/POWER_STATE/set",
      "power_state_topic": f"{self.topic_prefix}/POWER_STATE/state",
      "mode_command_topic": f"{self.topic_prefix}/UNIT_MODE/set",
      "mode_state_topic": f"{self.topic_prefix}/UNIT_MODE/state",
      "current_temperature_topic": f"{self.topic_prefix}/TEMP_INDOOR",
      "temperature_command_topic": f"{self.topic_prefix}/TEMP_PRESET/set",
      "temperature_state_topic": f"{self.topic_prefix}/TEMP_PRESET/state",
      "fan_mode_command_topic": f"{self.topic_prefix}/FAN_MODE/set",
      "fan_mode_state_topic": f"{self.topic_prefix}/FAN_MODE/state",
      "swing_mode_command_topic": f"{self.topic_prefix}/SWING_STATE/set",
      "swing_mode_state_topic": f"{self.topic_prefix}/SWING_STATE/state"
    }
    self.discovery_create_control('climate', unique_name, config)
    # POWER_STATE switch
    object_id = unique_name + "_power_state"
    config = {
      "object_id": object_id,
      "unique_id": object_id,
      "name": f"{self.room_name} HVAC Power State",
      "icon": "mdi:power",
      "availability_topic": f"{self.topic_prefix}/connection_state",
      "command_topic": f"{self.topic_prefix}/POWER_STATE/set",
      "state_topic": f"{self.topic_prefix}/POWER_STATE/state",
      "device": {
        "identifiers": unique_name
      }
    }
    self.discovery_create_control('switch', object_id, config)
    # SWING_STATE switch
    object_id = unique_name + "_swing_state"
    config = {
      "object_id": object_id,
      "unique_id": object_id,
      "name": f"{self.room_name} HVAC Swing State",
      "icon": "mdi:wall-sconce-flat",
      "availability_topic": f"{self.topic_prefix}/connection_state",
      "command_topic": f"{self.topic_prefix}/SWING_STATE/set",
      "state_topic": f"{self.topic_prefix}/SWING_STATE/state",
      "payload_on": "on",
      "payload_off": "off",
      "device": {
        "identifiers": unique_name
      }
    }
    self.discovery_create_control('switch', object_id, config)
    # UNIT_MODE selector
    object_id = unique_name + "_unit_mode"
    config = {
      "object_id": object_id,
      "unique_id": object_id,
      "name": f"{self.room_name} HVAC Unit Mode",
      "icon": "mdi:cog",
      "availability_topic": f"{self.topic_prefix}/connection_state",
      "command_topic": f"{self.topic_prefix}/UNIT_MODE/set",
      "state_topic": f"{self.topic_prefix}/UNIT_MODE/state",
      "options": ["auto", "cool", "heat", "dry", "fan_only", "off"],
      "device": {
        "identifiers": unique_name
      }
    }
    self.discovery_create_control('select', object_id, config)
    # FAN_MODE selector
    object_id = unique_name + "_fan_mode"
    config = {
      "object_id": object_id,
      "unique_id": object_id,
      "name": f"{self.room_name} HVAC Fan Mode",
      "icon": "mdi:fan",
      "availability_topic": f"{self.topic_prefix}/connection_state",
      "command_topic": f"{self.topic_prefix}/FAN_MODE/set",
      "state_topic": f"{self.topic_prefix}/FAN_MODE/state",
      "options": ["QUIET", "1", "2", "3", "4", "5", "AUTO"],
      "device": {
        "identifiers": unique_name
      }
    }
    self.discovery_create_control('select', object_id, config)
    # SPECIAL_MODE selector
    object_id = unique_name + "_special_mode"
    config = {
      "object_id": object_id,
      "unique_id": object_id,
      "name": f"{self.room_name} HVAC Special Mode",
      "icon": "mdi:fan-plus",
      "availability_topic": f"{self.topic_prefix}/connection_state",
      "command_topic": f"{self.topic_prefix}/SPECIAL_MODE/set",
      "state_topic": f"{self.topic_prefix}/SPECIAL_MODE/state",
      "options": ["-", "HIPOWER", "ECO/CFTSLP", "8C", "SILENT1", "SILENT2", "FRPL1", "FRPL2"],
      "device": {
        "identifiers": unique_name
      }
    }
    self.discovery_create_control('select', object_id, config)
    # TEMP_PRESET input
    object_id = unique_name + "_temp_preset"
    config = {
      "object_id": object_id,
      "unique_id": object_id,
      "name": f"{self.room_name} HVAC Temperature Setting",
      "icon": "mdi:thermometer-lines",
      "availability_topic": f"{self.topic_prefix}/connection_state",
      "command_topic": f"{self.topic_prefix}/TEMP_PRESET/set",
      "state_topic": f"{self.topic_prefix}/TEMP_PRESET/state",
      "min": "17",
      "max": "32",
      "unit_of_measurement": "°C",
      "device": {
        "identifiers": unique_name
      }
    }
    self.discovery_create_control('number', object_id, config)
    # POWER_SEL input
    object_id = unique_name + "_power_sel"
    config = {
      "object_id": object_id,
      "unique_id": object_id,
      "name": f"{self.room_name} HVAC Power Selection",
      "icon": "mdi:signal-cellular-2",
      "availability_topic": f"{self.topic_prefix}/connection_state",
      "command_topic": f"{self.topic_prefix}/POWER_SEL/set",
      "state_topic": f"{self.topic_prefix}/POWER_SEL/state",
      "min": "50",
      "max": "100",
      "step": "25",
      "unit_of_measurement": "%",
      "device": {
        "identifiers": unique_name
      }
    }
    self.discovery_create_control('number', object_id, config)
    # TEMP_INDOOR sensor
    object_id = unique_name + "_temp_indoor"
    config = {
      "object_id": object_id,
      "unique_id": object_id,
      "name": f"{self.room_name} HVAC Indoor Temperature",
      "availability_topic": f"{self.topic_prefix}/connection_state",
      "state_topic": f"{self.topic_prefix}/TEMP_INDOOR",
      "state_class": "measurement", 
      "unit_of_measurement": "°C", 
      "device_class": "temperature",
      "device": {
        "identifiers": unique_name
      }
    }
    self.discovery_create_control('sensor', object_id, config)
    # TEMP_OUTDOOR sensor
    object_id = unique_name + "_temp_outdoor"
    config = {
      "object_id": object_id,
      "unique_id": object_id,
      "name": f"{self.room_name} HVAC Outdoor Temperature",
      "availability_topic": f"{self.topic_prefix}/connection_state",
      "state_topic": f"{self.topic_prefix}/TEMP_OUTDOOR",
      "state_class": "measurement", 
      "unit_of_measurement": "°C", 
      "device_class": "temperature",
      "device": {
        "identifiers": unique_name
      }
    }
    self.discovery_create_control('sensor', object_id, config)
    # Last_refresh sensor
    object_id = unique_name + "_last_refresh"
    config = {
      "object_id": object_id,
      "unique_id": object_id,
      "name": f"{self.room_name} HVAC Last Full Refresh",
      "icon": "mdi:eye-refresh",
      "state_topic": f"{self.topic_prefix}/last_refresh",
      "device": {
        "identifiers": unique_name
      }
    }
    self.discovery_create_control('sensor', object_id, config)
    # Log messages sensor
    object_id = unique_name + "_log_message"
    config = {
      "object_id": object_id,
      "unique_id": object_id,
      "name": f"{self.room_name} HVAC Log Message",
      "icon": "mdi:format-list-bulleted-type",
      "state_topic": f"{self.topic_prefix}/log_message",
      "device": {
        "identifiers": unique_name
      }
    }
    self.discovery_create_control('sensor', object_id, config)
    # Connection state sensor
    object_id = unique_name + "_connection_state"
    config = {
      "object_id": object_id,
      "unique_id": object_id,
      "name": f"{self.room_name} HVAC Connection State",
      "state_topic": f"{self.topic_prefix}/connection_state",
      "payload_on": "online",
      "payload_off": "offline",
      "device_class": "connectivity",
      "device": {
        "identifiers": unique_name
      }
    }
    self.discovery_create_control('binary_sensor', object_id, config)
    # Refresh button
    object_id = unique_name + "_refresh"
    config = {
      "object_id": object_id,
      "unique_id": object_id,
      "name": f"{self.room_name} HVAC Refresh States",
      "icon": "mdi:refresh",
      "command_topic": f"{self.topic_prefix}/last_refresh",
      "payload_press": "-",
      "device": {
        "identifiers": unique_name
      }
    }
    self.discovery_create_control('button', object_id, config)
    self.log_main("Discovery config created")

  # Subscribe to MQTT topics and register its listeners
  def register_listeners(self):
    self.log_debug(f"register_listeners()")
    # refresh request listener
    topic = self.topic_prefix + "/" + "last_refresh"
    self.mqtt_subscribe(self.topic_prefix + "/" + "last_refresh", namespace="mqtt")
    self.listen_event(self.refresh_request, "MQTT_MESSAGE", topic=topic, namespace="mqtt")
    # state listeners
    for state in self.states:
      # do not register temperature settings
      if (state == "TEMP_INDOOR" or state == "TEMP_OUTDOOR"):
        continue # indoor/outdoor temp cannot be set
      else:
        topic = self.topic_prefix + "/" + state + "/set" # set for "MQTT Climate"
      self.mqtt_subscribe(topic, namespace="mqtt")
      self.listen_event(self.event_received, "MQTT_MESSAGE", topic=topic, namespace="mqtt", state=state)
      self.log_debug(f"Subscribed and registered listener for: {topic}")
    self.log_main("Listeners registered")  

  # Forced states refresh (by HA button)
  def refresh_request(self, event_name, data, kwargs):
    value = data['payload']
    self.log_debug(f"refresh_request('{value}')")
    if (value == "-"):
      self.log_set("States refresh requested...")
      if (self.get_all_states()):
        self.log_main("States refresh done")
      else:
        self.log_main("ERROR: States refresh failed")
    else:
      self.log_debug("Refresh requsest omitted")

  # Handle MQTT setting event  
  def event_received(self, event_name, data, kwargs):
    state = kwargs['state']
    value = data['payload']
    self.log_debug(f"event_received('{state}', '{value}')")
    # value correction
    if (not value):
      self.log_debug("Empty value, no action")
      return
    self.set_state(state, value)
 
  # Get state from HVAC and publish to MQTT  
  # returns: [str] state result
  def get_state(self, state):
    self.log_debug(f"get_state('{state}')")
    # GET HVAC STATE
    result = self.hvac_query(state)
    result = str(result) # all states as string including errors for easy final evaluation
    if (result.lower() == "false"):
      self.log_hvac(f"ERROR: State query failed ({state})")
      self.log_debug("No result")
      return result
    if (result == "-" and state != "SPECIAL_MODE"):
      self.log_debug("Unknown state")
      return result
    # convert for MQTT (HA)
    if (state == "UNIT_MODE" or state == "SWING_STATE"):
      result = result.lower()
    # publish to MQTT
    if (state == "TEMP_INDOOR" or state == "TEMP_OUTDOOR"):
      topic = self.topic_prefix + "/" + state # read-only values
    else:  
      topic = self.topic_prefix + "/" + state + "/state"
    self.mqtt_publish(topic, result, qos=1, namespace="mqtt")
    self.log_hvac(f"Query success ({state}: {result})")
    self.log_debug(f"{state}: {result}")
    return result
  
  # Get all states one by one (app_lock for polling to avoid concurrent runs)
  # returns: [bool] success
  def get_all_states(self, kwargs = None):
    self.log_debug(f"get_all_states()")
    if (self.callback_lock):
      self.log_main("Callback lock is set, skipping get_all_states() run")
      return False # avoid callback conflicts
    self.callback_lock = True
    power_state = self.get_state('POWER_STATE')
    if (power_state.lower() == "false"): 
      self.callback_lock = False
      return False # connection error, skip state querying
    for state in self.states:
      if (state == "POWER_STATE"):
          continue # the state is previously known
      if (power_state == 'OFF' and state == 'UNIT_MODE'):
        self.set_state('UNIT_MODE', 'off')
        self.log_debug("UNIT_MODE to off due to to power off")
        continue # HA mode setting workaround (one of unit modes is power off)
      result = self.get_state(state)
      if (result.lower() == "false"):
        self.callback_lock = False
        return False # connection error, skip state querying
    topic = self.topic_prefix + "/last_refresh"
    #value = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    value = datetime.datetime.now().strftime("%H:%M:%S")
    self.mqtt_publish(topic, value, qos=1, namespace="mqtt")
    self.callback_lock = False
    return True #
  
  # Get only temperature values (app_lock for polling to avoid concurrent runs)
  # returns: [bool] success
  def get_temps(self, kwargs = None):
    self.log_debug(f"get_temps()")
    if (self.callback_lock):
      self.log_main("Callback lock is set, skipping get_temps() run")
      return False # avoid callback conflicts
    self.callback_lock = True
    self.get_state('TEMP_INDOOR')
    self.get_state('TEMP_OUTDOOR')
    self.callback_lock = False
    return True

  # Set value to state and get actual (new) state from HVAC
  # returns: [bool] success  
  def set_state(self, state, value):
    self.log_debug(f"set_state('{state}', '{value}')")
    topic = self.topic_prefix + "/" + state + "/state" # this MQTT topic
    # value correction
    if (state == "UNIT_MODE" and value == "off"):
      # dummy mode for power off (HA triggering POWER_STATE to "OFF" by itself)
      self.mqtt_publish(topic, value, qos=1, namespace="mqtt")
      self.log_debug("Power off, no action")
      return False
    self.log_set(f"{state}: {value}") 
    if ("." in value):
      value = str(int(float(value)))
      self.log_debug("Value converted to INT")
    # SET HVAC STATE
    if (not self.hvac_command(state, value)):
      self.log_set("ERROR")
      return False
    # UPDATE MQTT
    # reflect SET state
    self.mqtt_publish(topic, value, qos=1, namespace="mqtt")
    # update to ACTUAL state
    result = self.get_state(state)
    if (result != value):
      self.log_set(f"Unconfirmed ({state}: {value} = {result})")
      return False
    self.log_set(f"Confirmed ({state}: {value})")
    # adapt UNIT_MODE state to POWER_STATE
    if (state == "POWER_STATE"):
      if (value == "ON"):
        self.get_state("UNIT_MODE") # get real state after manual powering on
      if (value == "OFF"):
        self.set_state("UNIT_MODE", "off") # adjust unit mode
    return True

  # Get connection state / report connection state to log/MQTT
  # returns: [bool] connection state (if no arguments)
  def connected(self, state = None):
    #self.log_debug(f"set_state('{connected}')") # commmented out due to log flooding
    if (state is None):
      return self.connected(self.is_connected) # just get actual state
    if (state):
      if (not self.is_connected and self.is_connected != None):
        self.log_main("Reconnected") # reconnection message
      self.is_connected = True
      topic = self.topic_prefix + "/connection_state"
      self.mqtt_publish(topic, "online", qos=1, namespace="mqtt")
      return True
    if (not state):
      if (self.is_connected is None):
        self.log_main("ERROR: Can't connect") # initial connection error message
      if (self.is_connected):
        self.log_main("ERROR: Disconnected") # disconnection message
      self.is_connected = False
      topic = self.topic_prefix + "/connection_state"
      self.mqtt_publish(topic, "offline", qos=1, namespace="mqtt")
      return False 


# === HVAC FUNCTIONS ===

  # Convert decimal string to HEX string
  # returns: [str] ex. '240' decimal converted to 'F0' HEX
  def decstr_to_hexstr(self, input):
    result = str(hex(int(input))).replace('0x', '').upper()
    if (len(result) < 2):
      result = "0" + result # missing leading zero
    return result

  # Convert received temperature from AC (to positive/negative value)
  # returns: [int] signed decimal value, [str] invalid value ("-")
  def convert_temperature(self, input_temperature):
    if (input_temperature == 127):
      return "-" # invalid value
    if (input_temperature > 127):
      return input_temperature - 256 # negative value
    return input_temperature # positive value

  # Send command to Tasmota
  # returns: [bool] error (False), [str] Tasmota response
  def tasmota_send(self, command): 
    self.log_tasmota(f"tasmota_command('{command}')")
    tasmota_command = f"http://{self.tasmota_host}/cm?user={self.tasmota_username}&password={self.tasmota_password}&cmnd="
    if (isinstance(command, list)):
      command = 'BackLog ' + '; '.join(command) # convert to one line Backlog
    tasmota_command += urllib.parse.quote_plus(command) 
    self.log_tasmota(tasmota_command)
    def get_response(url, retry_counter = 0):
      try:
        with urllib.request.urlopen(url, timeout=3) as response:
          result = response.read()
      except:
        # response problem = retry
        retry_counter += 1
        if (retry_counter == 1):
          self.log_tasmota(f"Connection error, immediate retry...")
          return get_response(url, retry_counter)
        if (retry_counter == 2):
          self.log_tasmota(f"Connection error, delayed retry...")
          time.sleep(2)
          return get_response(url, retry_counter)
        if (retry_counter == 3):
          self.log_tasmota(f"Connection error")
          return False
      # response received
      return result
    result = get_response(tasmota_command)
    if (self.connected and not result):
      self.log_tasmota("ERROR: Connection failed")
      self.connected(False) 
      return False
    self.log_tasmota("Connection success")
    self.connected(True) 
    result = str(result).replace("b'{", "{").replace("}'", "}")
    self.log_tasmota(f"Result: {result}")
    return result

  # Calculate checksum for HEX string command
  # returns: [str] HEX checksum (ex. 'F0')
  def hvac_checksum(self, input_command):
    command_list = re.findall('..', input_command) # split into list by regex
    del command_list[0] # remove start byte (02)
    int_array = []
    for val in command_list:
      int_array.append(int(val, 16))
    checksum = (0x100-(sum(int_array)%0x100))%0x100 # Pajtnovej fujtajbl
    checksum = str(hex(checksum)).replace('0x', '').upper()
    if (len(checksum) < 2):
      checksum = '0' + checksum # missing leading zero
    return checksum
  
  # Get value from HVAC
  # returns: [bool] error (False), [int] temperature, [str] function value
  def hvac_query(self, input_function, num_retries = 4, retry_counter = 0, response_only = False):
    self.log_hvac(f"hvac_query('{input_function}')")
    query_command_prefix = '020003100000060130010001'
    query_result_variable = 'Var2'
    if (not response_only):
      # prepare query
      query_command = query_command_prefix
      query_command += self.decstr_to_hexstr(self.function_codes[input_function]) # ex. 020003100000060130010001+BB (room temp)
      query_command += self.hvac_checksum(query_command) # ex. 020003100000060130010001BB+F9 (checksum)
      # send query
      command = []
      command.append(query_result_variable + " " + input_function) # clear query result variable 
      command.append('SerialSend5 ' + query_command) # query command (prefix + query code + checksum)
      if (not self.tasmota_send(command)):
        return False
    time.sleep(0.5) # time for HVAC response (500 ms)
    # get response
    response = self.tasmota_send(query_result_variable) # get query result variable
    if (not response):
      return False
    response = json.loads(response) # convert to JSON object {"Var2":"0200039000000901300100000002BB17"}
    response = response[query_result_variable] # get query variable value
    # check response
    query_response_prefix = '0200039000000901300100000002'
    query_response_prefix += self.decstr_to_hexstr(self.function_codes[input_function]) # prefix + query code
    valid_response = query_response_prefix in response
    if (not valid_response):
      # retry
      self.log_hvac("ERROR: Query response not valid")
      if (retry_counter == num_retries):
        return False; # no more retries
      retry_counter += 1
      return self.hvac_query(input_function, num_retries, retry_counter, retry_counter%2 == 1) # even retry = retry whole query, odd retry = re-read response
    # parse response
    result = response.replace(query_response_prefix, '')[0:2] # value is 2 chars after prefix
    result = int(result, 16) # convert HEX to decimal
    if ('TEMP_' in input_function):
      return self.convert_temperature(result) # temperature value [int|str="-"]
    result = str(result)
    if (input_function in self.function_values):
      return self.function_values[input_function][result] # translate if known [str]
    return result; # decimal value [str]

  # Send value to HVAC
  # returns: [bool]
  def hvac_command(self, input_function, input_value, num_retries = 4, retry_counter = 0, response_only = False):
    self.log_hvac(f"hvac_command('{input_function}', '{input_value}')")
    original_input_value = input_value
    control_command_prefix = '020003100000070130010002'
    command_result_variable = 'Var3'
    if (not response_only): 
      if (input_function == 'SPECIAL_MODE' and ('SILENT' in input_value)):
        self.hvac_command('POWER_SEL', '100', num_retries, retry_counter); # set maximum power in silent mode (same as over IR)
        self.get_state('POWER_SEL') # refresh HA state
      # prepare command
      control_command = control_command_prefix
      control_command += self.decstr_to_hexstr(self.function_codes[input_function]) # function code
      # try parse input value
      if (input_function != 'TEMP_PRESET'):
        try:
          input_value = list(self.function_values[input_function].keys())[list(self.function_values[input_function].values()).index(input_value)]
        except:
          self.log_hvac(f"ERROR: Unknown function value ('{input_value}')")
          return False
      elif (not input_value.isnumeric()):
        self.log_hvac(f"ERROR: Temperature value is not valid ('{input_value}')")
        return False 
      control_command += self.decstr_to_hexstr(input_value) # value
      control_command += self.hvac_checksum(control_command)
      # send command
      command = []
      command.append(command_result_variable + " " + input_function) # clear command result variable (set function code for console debug)
      command.append('SerialSend5 ' + control_command) # // query command (prefix + query code + checksum)
      if (not self.tasmota_send(command)):
        return False
    time.sleep(0.5) # time for AC response (500 ms)
    # get response
    response = self.tasmota_send(command_result_variable) # get query result variable
    if (not response):
      return False
    response = json.loads(response) # convert to JSON object {"Var2":"02000390000008013001000000018017"}
    response = response[command_result_variable] # get query variable value
    # check response
    command_response_prefix = '0200039000000801300100000001'
    command_response_prefix += self.decstr_to_hexstr(self.function_codes[input_function]) # prefix + query code
    valid_response = command_response_prefix in response
    if (not valid_response):
      # retry
      self.log_hvac("ERROR: Command response not valid")
      if (retry_counter == num_retries):
        return False # no more retries
      retry_counter += 1
      return self.hvac_command(input_function, original_input_value, num_retries, retry_counter, retry_counter%2 == 1) # even retry = retry whole command, odd retry = re-read response
    self.log_hvac("Command success")
    return True
    

# === LOGGING ===

  # Main logging (every log output)
  def log_main(self, message):
    self.log(message)
    topic = self.topic_prefix + "/log_message"
    self.mqtt_publish(topic, message, qos=1, namespace="mqtt")

  # Setting operations logging
  def log_set(self, message):
    if (self.set_log):
      self.log_main("SET: " + message)

  # Debug logging
  def log_debug(self, message):
    if (self.debug_log):
      self.log_main(message)
  
  # HVAC operations logging
  def log_hvac(self, message):
    if (self.hvac_log):
      self.log_main("HVAC: " + message)
  
  # Tasmota communication logging
  def log_tasmota(self, message):
    if (self.tasmota_log):
      self.log_main("TASMOTA: " + message)


# === MAIN ===
  
  # Replace language-specific characters
  def remove_accents (self, input_string):
    nfkd_form = unicodedata.normalize('NFKD', input_string)
    result = u"".join([c for c in nfkd_form if not unicodedata.combining(c)])
    return result

  # Remove accents, convert to lower-case and replace spaces with underscores
  def normalize_string(self, input_string):
    result = self.remove_accents(input_string)
    result = result.lower()
    result = result.replace(" ", "_")
    return result

  # Entrypoint  
  def initialize(self):
    self.log("=== TOSHIBA HVAC CONTROL ===")
    # config variables
    self.set_log = self.args['set_log']
    self.debug_log = self.args['debug_log']
    self.hvac_log = self.args['hvac_log']
    self.tasmota_log = self.args['tasmota_log']
    self.tasmota_host = self.args['tasmota_host']
    self.tasmota_password = self.args['tasmota_password']
    self.room_name = self.args['room_name']
    self.full_polling_sec = self.args['full_polling_sec']
    self.temps_polling_sec = self.args['temps_polling_sec']
    self.scheduler_pin_thread = self.args['scheduler_pin_thread']
    self.topic_prefix = self.normalize_string(f"{self.topic_group}/{self.room_name}")
    # init
    self.log_main(f"Room: {self.remove_accents(self.room_name)}") # unaccent for log
    self.log_debug(f"MQTT topic prefix: {self.topic_prefix}")
    self.log_debug(f"Tasmota host: {self.tasmota_host}")
    self.discovery_config()
    self.register_listeners()
    self.log_main("Initial states reading...")
    if (self.get_all_states()):
      self.log_main("States reading done")
    else:
      self.log_main("ERROR: States reading failed")
    # state polling (own separated thread)
    if (self.full_polling_sec):
      self.log_debug(f"Full polling seconds: {self.full_polling_sec}")
      self.run_every(self.get_all_states, "now + 10", self.full_polling_sec, pin=True, pin_thread=self.scheduler_pin_thread) # poll 10 seconds after init
    if (self.temps_polling_sec):
      self.log_debug(f"Temps polling seconds: {self.temps_polling_sec}")
      self.run_every(self.get_temps, "now + 20", self.temps_polling_sec, pin=True, pin_thread=self.scheduler_pin_thread) # poll 20 seconds after init
    if (self.full_polling_sec or self.temps_polling_sec):
      self.log_main("State polling set")
    self.log_main("= INIT COMPLETED =")

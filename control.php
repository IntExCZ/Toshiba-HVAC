<?php
	/*
	 USAGE:
	 	// host parameters (password is optional)
			?host=%host%&username=%username%&password(=%password%)
	 	
	 	// get HVAC state (desired state only if specified)
			&getstate(=%statename%) 
		
		// send command with value to HVAC
			&sendcmd=%cmdname%&cmdval=%cmdvalue%
		
		// init Tasmota environment
			&setup
		
		// scan HVAC states (desired state only if specified) + (number of retries)
			&debugstate(=%statename%)(&numretries=%retries_count%)
	*/

	$debug_mode = false;
	$admin = 'IntEx';

	/* Function constants (decimal) */
	$function_codes['TEMP_PRESET']	= '179'; // 17-32 degrees
	$function_codes['TEMP_INDOOR']	= '187';
	$function_codes['TEMP_OUTDOOR'] = '190';
	$function_codes['POWER_STATE']	= '128';
	$function_codes['POWER_SEL']	= '135'; // 50/75/100
	$function_codes['TIMER_ON']		= '144';
	$function_codes['TIMER_OFF']	= '148';
	$function_codes['FAN_MODE']		= '160';
	$function_codes['SWING_STATE']	= '163';
	$function_codes['UNIT_MODE']	= '176';
	$function_codes['SPECIAL_MODE'] = '247';

	$function_values['POWER_STATE'] 	= array('0' => '-', '48' => 'ON', '49' => 'OFF');
	$function_values['FAN_MODE']		= array('0' => '-', '49' => 'QUIET', '50' => '1', '51' => '2', '52' => '3', '53' => '4', '54' => '5', '65' => 'AUTO');
	$function_values['SWING_STATE'] 	= array('0' => '-', '49' => 'OFF', '65' => 'ON');
	$function_values['UNIT_MODE']		= array('0' => '-', '65' => 'AUTO', '66' => 'COOL', '67' => 'HEAT', '68' => 'DRY', '69' => 'FAN');
	$function_values['POWER_SEL']		= array('50' => '50%', '75' => '75%', '100' => '100%');
	$function_values['SPECIAL_MODE']	= array('0' => '-', '1' => 'HIPOWER', '3' => 'ECO/CTSP', '4' => '8C', '2' => 'SILENT-1', '10' => 'SILENT-2', '32' => 'FRPL1', '48' => 'FRPL2'); // CTSP = Comfort Sleep
	$function_values['TIMER_ON']		= array('65' => 'ON', '66' => 'OFF');
	$function_values['TIMER_OFF']		= array('65' => 'ON', '66' => 'OFF');
	
	// Debug output message
	// returns: none (output to stdout)
	function debug_out($message = null, $force = false) {
		global $debug_mode;
		if (!$debug_mode && !$force)
			return;
		echo $message."\n";
	}

	// Convert decimal to HEX
	// returns: uppecrace HEX with leading zero
	function to_hex($input) {
		$result = dechex($input);
		$result = strtoupper($result); // uppercase
		if (strlen($result) < 2)
			$result = '0'.$result; // leading zero
		return $result; 
	}

	// Send command to Tasmota
	// returns: Tasmota response
	function tasmota_send($command) {
		global $tasmota_host, $tasmota_username, $tasmota_password;
		$tasmota_command = "http://$tasmota_host/cm?user=$tasmota_username&password=$tasmota_password&cmnd=";
		if (is_array($command))
			$command = 'BackLog '.implode('; ', $command); // convert to one line Backlog
		$tasmota_command .= rawurlencode($command); 
		debug_out($tasmota_command);
		$result = file_get_contents($tasmota_command);
		if (!$result) {
			$status_line = $http_response_header[0];	
			if (!$status_line) {
				$status_code = 503;
				$status_line = "Unable to connect to host '".$tasmota_host."'.";
			} else {
				preg_match('{HTTP\/\S*\s(\d{3})}', $status_line, $match);
				$status_code = $match[1];
			}
			http_response_code($status_code);
			die("Error: " . $status_line);
		}
		debug_out($result);
		debug_out();
		return $result;
	}

	// Setup environment parameters in Tasmota
	// returns: none
	function tasmota_setup() {
		// serial port parameters
		tasmota_send('SerialConfig 8E1');
		tasmota_send('Baudrate 9600');
		// keep-alive polling (indoor temperature query every minute)
		tasmota_send('Rule1 ON Time#Minute DO SerialSend5 020003100000060130010001BBF9 ENDON');
		tasmota_send('Rule1 1');
		// query/command response variables updating (store query response in Var2, store command response in Var3)
		tasmota_send('Rule2 ON SerialReceived#Data$<0200039000000901300100000002 DO Var2 %value% ENDON ON SerialReceived#Data$<0200039000000801300100000001 DO Var3 %value% ENDON');
		tasmota_send('Rule2 1');
		// HVAC init (handshake + aftershake) on WiFi connected (SerialConfig = Wemos D1 Mini Pro restart workaround)
		tasmota_send('Rule3 ON Wifi#Connected DO Backlog SerialConfig 8O1; SerialConfig 8E1; Delay 10; SerialSend5 02FFFF0000000002; SerialSend5 02FFFF0100000102FE; SerialSend5 020000000000020202FA; SerialSend5 0200018101000200007B; SerialSend5 020001020000020000FB; SerialSend5 02000200000000FE; Delay 20; SerialSend5 020002010000020000FB; SerialSend5 020002020000020000FA ENDON');
		tasmota_send('Rule3 1');
	}

	// Convert received temperature from HVAC (to positive/negative value)
	// returns: signed decimal value
	function convert_temperature($input_temperature) {
		if ($input_temperature == 127)
			return '-'; // invalid value
		if ($input_temperature > 127)
			return $input_temperature - 256; // negative value
		return $input_temperature; // positive value
	}

	// Calculate checksum for command
	// returns: HEX checksum
	function hvac_checksum($input_command) {
		$command_array = str_split($input_command, 2); // convert to array
		array_shift($command_array); // remove start byte (02)
		$command_array = array_map('hexdec', $command_array); // convert to decimals
		$checksum = array_sum($command_array); // calculate sum of bytes
		$checksum = (256-($checksum)%256)%256; // calculate checksum
		$checksum = to_hex($checksum);
		return $checksum;
	}

	// Send Handshake + aftershake to HVAC
	// returns: none
	function hvac_init() {
		$command = [];
		array_push($command, 'SerialSend5 02FFFF0000000002');
		array_push($command, 'SerialSend5 02FFFF0100000102FE');
		array_push($command, 'SerialSend5 020000000000020202FA');
		array_push($command, 'SerialSend5 0200018101000200007B');
		array_push($command, 'SerialSend5 020001020000020000FB');
		array_push($command, 'SerialSend5 02000200000000FE');
		array_push($command, 'Delay 20');
		array_push($command, 'SerialSend5 020002010000020000FB');
		array_push($command, 'SerialSend5 020002020000020000FA');
		tasmota_send($command);
		sleep(2);
	} 

	// Send command to HVAC (with result check+retry)
	// example: hvac_command('POWER_STATE', 'ON');
	// returns: true/false (command success/fail)
	$hvac_command_retries = []; // command retries log
	function hvac_command($input_function, $input_value, $num_retries = 4, $retry_counter = 0, $response_only = false) {
		global $function_codes, $function_values;
		global $hvac_command_retries;
		$original_input_value = $input_value; // for eventual retry
        $control_command_prefix = '020003100000070130010002';
		$command_result_variable = 'Var3';
		if (!$response_only) {
			if ($input_function == 'SPECIAL_MODE' && strpos($input_value, 'SILENT') !== false)
				hvac_command('POWER_SEL', '100%', $num_retries, $retry_counter); // set maximum power in silent mode (same as over IR)
			// prepare command
			$control_command = $control_command_prefix;
			$control_command .= to_hex($function_codes[$input_function]); // function code
			if ($input_function != 'TEMP_PRESET')
				$input_value = array_search($input_value, $function_values[$input_function]);
			$control_command .= to_hex($input_value); // value
			$control_command .= hvac_checksum($control_command);
			// send command
			$command = [];
			array_push($command, $command_result_variable." ".$input_function); // clear command result variable (set function code for console debug)
			array_push($command, 'SerialSend5 '.$control_command); // query command (prefix + query code + checksum)
			tasmota_send($command);
		}
		usleep(500000); // time for HVAC response (500 ms)
		// get response
		$response = tasmota_send($command_result_variable); // get query result variable
		$response = json_decode($response); // convert to JSON object {"Var2":"02000390000008013001000000018017"}
		$response = $response->{$command_result_variable}; // get query variable value
		// check response
		$command_response_prefix = '0200039000000801300100000001';
		$command_response_prefix .= to_hex($function_codes[$input_function]); // prefix + query code
		$valid_response = (strpos($response, $command_response_prefix) !== false);
		if (!$valid_response) {
			if ($retry_counter == $num_retries)
				return false; // no more retries
			$retry_counter++;
			array_push($hvac_command_retries, $input_function.": ".$retry_counter.". retry");
			return hvac_command($input_function, $original_input_value, $num_retries, $retry_counter, $retry_counter%2 == 1); // even retry = retry whole command, odd retry = re-read response
		}
		return true;
	}

	// Query HVAC state (with result check+retry)
	// returns: decimal temperature/translated value/
	$hvac_query_retries = []; // query retries log
	$ac_state_valid = true; // query validity flag (if all states were retrieived)
	function hvac_query($input_function, $num_retries = 4, $retry_counter = 0, $response_only = false) {
		global $function_codes, $function_values;
		global $hvac_query_retries, $ac_state_valid;
		$query_command_prefix = '020003100000060130010001';
		$query_result_variable = 'Var2';
		if (!$response_only) {
			// prepare query
			$query_command = $query_command_prefix;
			$query_command .= to_hex($function_codes[$input_function]); // ex. 020003100000060130010001+BB (room temp)
			$query_command .= hvac_checksum($query_command); // ex. 020003100000060130010001BB+F9 (checksum)
			// send query
			$command = [];
			array_push($command, $query_result_variable." ".$input_function); // clear query result variable (set function code for console debug)
			array_push($command, 'SerialSend5 '.$query_command); // query command (prefix + query code + checksum)
			tasmota_send($command);
		}
		usleep(500000); // time for HVAC response (500 ms)
		// get response
		$response = tasmota_send($query_result_variable); // get query result variable
		$response = json_decode($response); // convert to JSON object {"Var2":"0200039000000901300100000002BB17"}
		$response = $response->{$query_result_variable}; // get query variable value
		// check response
		$query_response_prefix = '0200039000000901300100000002';
		$query_response_prefix .= to_hex($function_codes[$input_function]); // prefix + query code
		$valid_response = (strpos($response, $query_response_prefix) !== false);
		if (!$valid_response) {
			if ($retry_counter == $num_retries) {
				$ac_state_valid = false;
				return false; // no more retries
			}
			$retry_counter++;
			array_push($hvac_query_retries, $input_function.": ".$retry_counter.". retry");
			return hvac_query($input_function, $num_retries, $retry_counter, $retry_counter%2 == 1); // even retry = retry whole query, odd retry = re-read response
		}
		// parse response
		$result = substr($response, strlen($query_response_prefix), 2); // value length = 2
		$result = hexdec($result);
		if (strpos($input_function, 'TEMP_') !== false)
			return convert_temperature($result); // temperature value
		if (array_key_exists($input_function, $function_values)) 
			return $function_values[$input_function][$result]; // translate if known
		return $result; // decimal value
	}

	// MAIN BODY (GET queries)
	$tasmota_host = isset($_GET['host']) ? $_GET['host'] : -1;
	$tasmota_username = isset($_GET['username']) ? $_GET['username'] : -1;
	$tasmota_password = isset($_GET['password']) ? $_GET['password'] : "";
	
	if ($debug_mode)
		echo "DEBUG_MODE"."\n";

	// get state
	$getstate = isset($_GET['getstate']) ? $_GET['getstate'] : -1; 
	if ($getstate != -1) {
		if (!$getstate) {
			// all states
			foreach ($function_codes as $key => $value) {
				$states[$key] = hvac_query($key);
			}
		} else {
			$getstate = strtoupper($getstate);
			if ($getstate == 'ENUM') {
				// expose possible values
				foreach ($function_codes as $key => $value) {
					$states[$key] = array_key_exists($key, $function_values) ? $function_values[$key] : null;
				}
			} else {
				// only defined states
				$getstate = explode(',', $getstate);
				foreach ($getstate as $state) {
					if (!array_key_exists($state, $function_codes)) {
						// state function unknown
						$ac_state_valid = false;
						$states[$state] = false;
					} else 
						$states[$state] = hvac_query($state);
				}
			}
		}
		header("HVAC-State-Valid: ".($ac_state_valid ? '1' : '0'));
		header("HVAC-Query-Retries: ".implode(', ', $hvac_query_retries));
		echo json_encode($states);
		exit;
	} 

	// send command
	$sendcmd = isset($_GET['sendcmd']) ? $_GET['sendcmd'] : -1;
	$cmdval = isset($_GET['cmdval']) ? $_GET['cmdval'] : -1;
	$cmdresult = [];
	if ($sendcmd != -1 && $cmdval != -1) {
		if (strtolower($_SERVER['REMOTE_USER']) != strtolower($admin)) {
			header('HTTP/1.0 403 Forbidden');
			die("Action not permitted!");
		}
		$sendcmd = strtoupper($sendcmd);
		$cmdval = strtoupper($cmdval);
		if ($sendcmd == 'TEMP_PRESET') {
			$cmdresult[$sendcmd.':'.$cmdval] = !is_numeric($cmdval) ? 'INVALID_TEMP' : hvac_command($sendcmd, $cmdval);
		} else {
			if (!array_key_exists($sendcmd, $function_values)) {
				if (is_numeric($sendcmd)) {
                    // manual command number
                    $cmdresult[$sendcmd.':'.$cmdval] = hvac_command($sendcmd, $cmdval);
                } else {
                    // command not known
                    $cmdresult[$sendcmd] = 'UNKNOWN_COMMAND';
                }
			} else {
                // known command
				$cmdresult[$sendcmd.':'.$cmdval] = !is_numeric(array_search($cmdval, $function_values[$sendcmd])) ? 'INVALID_VALUE' : hvac_command($sendcmd, $cmdval);
		    }
        }
		header("AC-Command-Retries: ".implode(', ', $hvac_command_retries));
		echo json_encode($cmdresult);
		exit;
	}

	// setup Tasmota environment
	if (isset($_GET['setup'])) {
		tasmota_setup();
		echo "Setup commands sent to '$tasmota_host'.";
		exit;
	}
    
	// get custom state
	$debugstate = isset($_GET['debugstate']) ? $_GET['debugstate'] : -1; 
	$numretries = isset($_GET['numretries']) ? $_GET['numretries'] : -1;
	if ($debugstate != -1) {
		$numretries = ($numretries != -1 && is_numeric($numretries)) ? $numretries : 1;		
		if (!$debugstate) {
			// fill function codes array with all codes
			for ($i=128; $i<255; $i++) {
				if (in_array($i, $function_codes))
					continue;
				$function_codes[$i] = $i;
			}
			asort($function_codes);
			foreach ($function_codes as $key => $value) {			
				$show_key = ($value != $key) ? $value." (".$key.")" : $key;
				$states[$show_key] = hvac_query($key, $numretries); // defined number of retries or 1
			}
		} else {
			$debugstate = strtoupper($debugstate);
			if (!array_key_exists($debugstate, $function_codes))
				$function_codes[$debugstate] = $debugstate; // add requested key to function codes
			$states[$debugstate] = hvac_query($debugstate, $numretries); // defined number of retries or 1
		}
		header("HVAC-State-Valid: ".($ac_state_valid ? '1' : '0'));
		header("HVAC-Query-Retries: ".implode(', ', $hvac_query_retries));
		foreach ($states as $key => $value) {
			echo "$key: $value"."\n";
		}
		echo "\n";
		echo json_encode($states);
	}

?>

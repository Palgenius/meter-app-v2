
from os import makedirs, path
import os
import json
import platform

import netifaces
from src.auto_detect import detect_meters, scan_ports




class Config:
    
    def __init__(self,filename):
        if path.dirname(filename):
            makedirs(path.dirname(filename), exist_ok=True)
        if not path.exists(filename):
            self.makeConfigFile(filename)
        self.config= self.loadConfig(filename)
        self.filename = filename
        
        # Auto-detect meters if list is empty, auto_detect flag is set,
        # OR configured ports don't exist on this system (wrong OS / bad config)
        self.info_meters = self.getConfigVal("meters")
        needs_detect = (
            not self.info_meters
            or self.getConfigVal("auto_detect", False)
            or self._ports_are_invalid(self.info_meters)
        )
        if needs_detect:
            self.info_meters = self._auto_detect_meters()
            self.setConfigVal("meters", self.info_meters)
        
        newinfos=[]
        i=0
        for info_meter in self.info_meters :
            # Phase 1.5: Validate meter config
            if not self._validate_meter(info_meter):
                print(f"[config] WARNING: Skipping invalid meter #{i+1}")
                continue
            info_meter["PanelID"]=self.mac_to_static_uuid(self.get_mac_address(),i)
            i+=1
            newinfos.append(info_meter)
        self.setConfigVal("meters",newinfos)
        self.save()
            
    def get_mac_address(self):
        interface = 'wlan0'
        try:
            mac = netifaces.ifaddresses(interface)[netifaces.AF_LINK][0]['addr']
            return mac.upper()
        except (KeyError, ValueError):
            return "00:00:00:00:00:00"

    def _ports_are_invalid(self, meters):
        """Check if configured meter ports exist on this system.
        
        Returns True if ANY meter has a port that doesn't exist —
        triggers auto-detection so the app figures out the right port.
        
        Handles:
          - Windows ports (COM12) on Linux
          - Missing serial devices
          - Empty/None ports
        """
        for meter in meters:
            port = meter.get("Serail_Port", "")
            if not port:
                print(f"[config] Meter {meter.get('MeterID', '?')} has no port — auto-detecting")
                return True

            # Windows COM ports on a Linux system
            if port.upper().startswith("COM") and platform.system() != "Windows":
                print(f"[config] Port '{port}' is Windows-only but running on {platform.system()} — auto-detecting")
                return True

            # Linux serial devices — check if the file exists
            if port.startswith("/dev/tty"):
                if not path.exists(port):
                    print(f"[config] Port '{port}' does not exist on this system — auto-detecting")
                    return True

            # Fallback: check against detected ports
            # (only if the port format doesn't match known patterns)
            if platform.system() == "Linux" and not port.startswith("/dev/"):
                available = scan_ports()
                if available and port not in available:
                    print(f"[config] Port '{port}' not found. Available: {available} — auto-detecting")
                    return True

        return False
    
    def _auto_detect_meters(self):
        """Auto-detect connected meters via serial port scanning.
        
        Returns list of meter info dicts compatible with config.json format.
        """
        print("[config] No meters configured — running auto-detection...")
        results = detect_meters()
        if not results:
            print("[config] No meters detected. Add meters manually to config.json.")
            return []
        
        meters = []
        for i, r in enumerate(results):
            meter = {
                "Meter_type": r["meter_type"],
                "MeterID": str(r["slave_id"]),
                "Serail_Port": r["port"],
                "Serial_Baudrate": r["baudrate"],
                "serial": False,
                "MQTT_topic": f"meter_{r['meter_type'].lower()}_{i+1}",
            }
            meters.append(meter)
            print(f"[config] Detected: {r['meter_type']} on {r['port']} @ {r['baudrate']} baud")
        
        print(f"[config] Auto-detected {len(meters)} meter(s)")
        return meters
    
    def mac_to_static_uuid(self,mac_address,num=0):
        # Clean the MAC address by removing any separators (like :, -)
        mac = mac_address.replace(':', '').replace('-', '')
        
        # Ensure the MAC address is 12 characters long (6 bytes)
        if len(mac) != 12:
            raise ValueError("ERROR: Invalid MAC address format")
        
        # Convert MAC address to an integer
        node = int(mac, 16)

        # Create a static UUID using the MAC address
        # Here we use a random timestamp and fixed clock sequence
        uuid_parts = [
            f"{num:08x}",  # Time low (placeholder)
            f"{0:04x}",  # Time mid (placeholder)
            f"{0x1000:04x}",  # Time high and version (version 1)
            f"{0x8000:04x}",  # Clock sequence (variant 1)
            f"{node:012x}"   # Node (MAC address)
        ]
        
        # Combine parts into the UUID format
        uuid_string = f"{uuid_parts[0]}-{uuid_parts[1]}-{uuid_parts[2]}-{uuid_parts[3]}-{uuid_parts[4]}"
        #logger.info(f"uuid_string: {uuid_string}")
        return uuid_string

       
    def setConfigVal(self,key,val):
        self.config[key]=val
    
    def getConfigVal(self,key,initial=None):
        
        try:
            return self.config.get(key,initial)
        except:
            return None

    # Phase 1.5: Config validation
    SUPPORTED_METER_TYPES = ["SPM32", "SMP20", "PMAC202", "PMAC211", "SPM206", "SMP20", "KITT", "KITTY"]
    VALID_BAUDRATES = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]

    def _validate_meter(self, meter_info):
        """Validate a single meter configuration. Returns True if valid."""
        # Check Meter_type
        meter_type = meter_info.get("Meter_type", "")
        if not meter_type or meter_type.upper() not in [t.upper() for t in self.SUPPORTED_METER_TYPES]:
            print(f"[config] WARNING: Unknown meter type '{meter_type}'")
            return False

        # Check Serail_Port (intentional misspelling kept)
        port = meter_info.get("Serail_Port", "")
        if not port or not isinstance(port, str) or len(port.strip()) == 0:
            print(f"[config] WARNING: Invalid serial port for meter {meter_type}")
            return False

        # Check Serial_Baudrate
        baud = meter_info.get("Serial_Baudrate", 0)
        if baud not in self.VALID_BAUDRATES:
            print(f"[config] WARNING: Invalid baud rate {baud} for meter {meter_type} (valid: {self.VALID_BAUDRATES})")
            return False

        # Check MeterID
        meter_id = meter_info.get("MeterID", "")
        if not str(meter_id).isdigit():
            print(f"[config] WARNING: Invalid MeterID '{meter_id}' for meter {meter_type}")
            return False

        # Check request_time
        request_time = self.getConfigVal("request_time", 1)
        if request_time <= 0:
            print(f"[config] WARNING: Invalid request_time {request_time}")
            return False

        return True
   
    def loadConfig(self, path=None):
        if(path == None):
            path=self.filename
        config_file = open(path,'r')
        return json.loads(config_file.read())

    def read_config(self):
        """Read current config from disk. Used by socket_server for config_read command."""
        try:
            self.config = self.loadConfig(self.filename)
            return self.config
        except Exception as e:
            print(f"[config] Error reading config: {e}")
            return {}

    def write_config(self, new_config):
        """Write new config to disk. Used by socket_server for config_write command."""
        try:
            self.config = new_config
            self.save(new_config)
            return True
        except Exception as e:
            print(f"[config] Error writing config: {e}")
            return False

    def saveConfig(self, data,path=None):
        if(path == None):
            path=self.filename
        config_file = open(path,'w')
        if type(data) is str:
            config_file.write(data)
            return True
        conf=json.loads(json.dumps(data))
        config_file.write(json.dumps(conf).replace(",", ",\n"))
        return True
     
    def save(self,data=None):

        if(data is not None):
            self.config=data
        else:
            data = self.config
        self.saveConfig(data,self.filename)

    def makeConfigFile(self,fileName):
        self.saveConfig("""
{
  "productionMode": false,
  "request_time":0.15,
  "database_file": "database/",

  "meters":[
 
  {"Meter_type": "SMP20",
    "PanelID" : "7e95d82bf2464a3690fa88809772054d",
    "MeterID" : "1",
    "MQTT_topic":"smp20",
    "Serail_Port": "/dev/ttyUSB",
    "Serial_Baudrate": 9600
   
  }],

 
  "Node": "SAN00014",

  "ZigBee_log_file_name":"logs/zigbee/",
  "ZigBee_log_enable": false,
  "visible_ZigBee_Log":false,
  "APP_log_file_name": "logs/app/",
  "APP_log_enable": true,
  "visible_App_Log":true,
  "MQTT_log_file_name": "logs/mqtt/",
  "MQTT_log_enable": true,
  "METER_log_file_name":"logs/meter/",
  "METER_log_enable": true,
  "log_file_max_size": 20,
  "log_max_files": 20,
  


  "MQTT_topic":"Tariq_home",
  "MQTT_broker_address":"localhost",
  "MQTT_broker_port": 1883,
  "MQTT_broker_tls":false,
  "MQTT_broker_ca_Path" : "certificate_keys/car-root-CA.crt",
  "MQTT_broker_cert_Path" : "certificate_keys/car-certificate.pem.crt",
  "MQTT_broker_key_Path" :"certificate_keys/car-private.pem.key",
  "MQTT_broker_tls_insecure": true
  
}

   
""",fileName)


    

    




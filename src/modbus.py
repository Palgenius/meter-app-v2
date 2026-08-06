from pymodbus.client.sync import ModbusSerialClient as ModbusClient
import time
import threading
# mbpoll -a 1 -b 9600 -t 3 -r 1 -c 2 /dev/ttyUSB0

CONNECT_TIMEOUT = 10  # seconds — kill connect() if serial port blocks


class Modbus:
   
    productionMode = True#False
    
    
    def __init__(self,meterformat,Serail_Port,Serial_Baudrate,productionMode,logger):
        self.lastAE_RE={}
        self.logger =logger
        self.recent_errors = []  # Collect errors for alert system
        self.meter=meterformat
        self._port = Serail_Port
        self._baudrate = Serial_Baudrate
        self.productionMode = productionMode
        
        if(self.productionMode):
            self.client = ModbusClient(method='rtu', port=self._port,
                                       baudrate=self._baudrate, stopbits=1, parity='N', bytesize=8, timeout=2)
            self._safe_connect(self.client, "modbus is connected")
            time.sleep(1)  # reduced from 2s to 1s settle time

    def _safe_connect(self, client, success_msg):
        """Connect with a timeout thread to prevent blocking on stuck serial ports."""
        result = [None]
        def _do_connect():
            try:
                result[0] = client.connect()
            except Exception as ex:
                result[0] = ex
        t = threading.Thread(target=_do_connect, daemon=True)
        t.start()
        t.join(timeout=CONNECT_TIMEOUT)
        if t.is_alive():
            self.logger.insert_Error_APP_log(
                f'modbus connect timed out after {CONNECT_TIMEOUT}s (port {self._port} stuck)')
            raise ConnectionError(f"Modbus connect timed out on {self._port}")
        if isinstance(result[0], Exception):
            raise result[0]
        self.logger.insert_Info_APP_log(success_msg)

    def closeConnection(self):
        self.logger.insert_Info_APP_log('modbus disconnected..')
        if(self.productionMode):
            try:
                self.client.close()
            except Exception:
                pass

    def reconnect(self):
        """Close and reopen the serial connection with a settle delay.
        
        Called when a read fails — the serial port may be in a bad state.
        Returns True if reconnected successfully.
        """
        if not self.productionMode:
            return True
        try:
            try:
                self.client.close()
            except Exception:
                pass
            time.sleep(0.5)
            self.client = ModbusClient(method='rtu', port=self._port,
                                       baudrate=self._baudrate, stopbits=1, parity='N', bytesize=8, timeout=2)
            self._safe_connect(self.client, 'modbus reconnected')
            time.sleep(0.5)  # settle the RS485 bus (reduced from 1s)
            return True
        except Exception as ex:
            self.logger.insert_Error_APP_log(f'modbus reconnect failed: {ex}')
            return False

    def _collect_error(self, msg):
        """Log error AND store it for the alert system to pick up.
        Includes source file and method for clear identification."""
        self.logger.insert_Error_APP_log(msg)
        self.recent_errors.append({
            "level": "ERROR",
            "message": msg,
            "source": "modbus.py/grapData",
            "time": time.time()
        })

    def get_and_clear_errors(self):
        """Return recent errors and clear the buffer. Called by app.py after each read cycle."""
        errors = self.recent_errors[:]
        self.recent_errors = []
        return errors



    def _read_payload(self, payload):
        """Read a Modbus payload, falling back to one-by-one if bulk read fails.
        
        Some meters (e.g. PMAC211) don't support bulk reads from certain
        address ranges. When the bulk read fails, we read each register
        individually. Failed registers get value 0.
        """
        addr = payload['address']
        count = payload['count']
        
        # Try bulk read first
        time.sleep(0.1)
        res = self.client.read_holding_registers(address=addr, count=count, unit=1)
        if not res.isError() and len(res.registers) == count:
            return res.registers
        
        # Bulk read failed or returned wrong count — read one-by-one
        actual = 0 if res.isError() else len(res.registers)
        self.logger.insert_Error_APP_log(
            f"Bulk read failed at addr={addr}, count={count} (got {actual}) — reading one-by-one")
        
        registers = []
        failed = 0
        for offset in range(count):
            time.sleep(0.03)
            r = self.client.read_holding_registers(address=addr + offset, count=1, unit=1)
            if r.isError():
                registers.append(0)  # use 0 for dead registers
                failed += 1
            else:
                registers.append(r.registers[0])
        if failed > 0:
            self.logger.insert_Error_APP_log(
                f"Single reads: {failed}/{count} failed at addr={addr} — using 0 for missing")
        return registers

    def grapData(self):
        if(self.productionMode):
            try:
                registers=[]
               
                for _payload in self.meter.READING_PAYLOADS:
                    regs = self._read_payload(_payload)
                    if regs is None:
                        self._collect_error("data is not graped res ..")
                        return None
                    registers += regs
                

            except Exception as ex:
                self._collect_error("data is not graped  ..")
                return None

        else:
            registers = self.meter.getsampleData()
        self.logger.insert_meter_log(registers)
##################################################################
        try:
            
            data= self.meter.decode(registers)
            if(self.check_data_interference(data)):
                self._collect_error("data interference happend ..")
                return None
                
            ae_re_keys = [key for key in data.keys() if 'AE' in key or 'RE' in key]
            for key in ae_re_keys:
                value = data[key]
                # Save raw cumulative value for 15-min aggregation (delta = last - first)
                data[key + '_cum'] = value
                data[key]=self.AE_RE_comulative_to_static(key,value)
                PPKey = key.replace('AE','P') if('AE' in key) else key.replace('RE','P') # THE POWER kEY 
                if (data[key]>0.02 and PPKey in data.keys() and data[PPKey]>0):
                    if((data[PPKey])/(data[key]*60)<.2): # COMPARE THE AE/RE WITH THE Enery IF IT IS less THAN 20% THEN IT is need to be divided by 10 
                        self._collect_error(f"energy spike corrected | {key}: {data[key]} , {PPKey}: {data[PPKey]}  time: {data['time']}")
                        data[key]=data[key]/10
               
            return self.tolowercase(data)#data
        except Exception as e:
            self._collect_error(f"data not completed .. {e}")
            return None
####################################################################################
    
    def tolowercase(self,data):
        d={}
        for key,value in data.items():
            d[key.lower()]=value
        return d
    def AE_RE_comulative_to_static(self,key,value):
        temp = 0.0
        if(key in self.lastAE_RE.keys()):
            temp =int(value*1000)-int(self.lastAE_RE[key]*1000)
            temp/=1000
        self.lastAE_RE[key]=value
        return temp    

    def check_data_interference(self,data):
        #'TPF': -9.447, 'TAE': 127753374.3, 'TRE': -234653893.0
        #print("data: ",data)
        tpf = abs(data.get('TPF', 0))
        tae = abs(data.get('TAE', 0))
        tre = abs(data.get('TRE', 0))
        # SPM32/SPM206 can legitimately report TPF up to ~3.0
        if (tpf > 3.0 or tae > 127753000 or tre > 127753000):
            self._collect_error(f"checking data interference | TPF:{data.get('TPF',0)}, TAE: {data.get('TAE',0)}, TRE: {data.get('TRE',0)} ,time: {data.get('time',0)}")
            return True
       
        #'AV': 0.0, 'BV': 0.0, 'CV': 0.0, 'V': 0.0, 'F': 0.0,
        if (data.get('V', 0) < 10):
            self._collect_error(f"checking data interference | V:{data.get('V',0)} F: {data.get('F',0)} time: {data.get('time',0)}")
            return True
        #print(data)
        return False

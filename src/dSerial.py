import json
import serial
import time
# mbpoll -a 1 -b 9600 -t 3 -r 1 -c 2 /dev/ttyUSB0


class DSerial:
   
    productionMode = True#False
    
    
    def __init__(self,meterformat,Serail_Port,Serial_Baudrate,productionMode,logger):
        self.lastAE_RE={}
        self.logger =logger
        self.meter=meterformat
        PORT = Serail_Port
        baudrate = Serial_Baudrate
        self.productionMode = productionMode
        
        if(self.productionMode):
            self.client = serial.Serial(Serail_Port, Serial_Baudrate)
            
            #self.logbytes = f"logs/log_{time.time()}.txt"
            self.logger.insert_Info_APP_log("serial is connected")
            time.sleep(2)

    def closeConnection(self):
        self.logger.insert_Info_APP_log('serial disconnected..')
        if(self.productionMode):
            self.client.close()



    def grapData(self):
        data = ""
        if(self.productionMode):
            try:
                registers={}
                self.client.reset_input_buffer()
                self.client.write(b"pushmm") 
                
                trying =2
                timeout = 2  # Timeout in seconds
                start_time = time.time()
                while True:
                    if self.client.in_waiting>0:
                        char = self.client.read().decode('utf-8', errors='replace')  # Read a single character and decode it from bytes to string
                        data += char
                        if char == '}':             
                            break    
                    # Check if timeout duration has passed
                    elapsed_time = time.time() - start_time
                    if elapsed_time > timeout:
                        if(trying>0):
                            trying-=1
                            start_time = time.time()
                            self.client.reset_input_buffer()
                            self.client.write(b"push00")
                            data=""                          
                            self.logger.insert_Error_APP_log("Timeout occurred. '}' character not received. trying agian ")
                        break
                # Convert the received data to a JSON object if '}' character was received
                if '}' in data:
                    
                    registers = json.loads(data.replace("nan","0.0"))
                else:
                    self.logger.insert_Error_APP_log("data is not graped res ..")
                    return None
                

            except Exception as ex:
                self.logger.insert_Error_APP_log("data is not graped  ..", ex)
                self.logger.insert_Error_APP_log("data >> ",data)
                return None

        else:
            registers = self.meter.getsampleData()
        self.logger.insert_meter_log(registers)
##################################################################
        try:
            
            data= self.meter.decode(registers)
            
            ae_re_keys = [key for key in data.keys() if 'AE' in key or 'RE' in key]
            for key in ae_re_keys:
                value = data[key]
                # Save raw cumulative value for 15-min aggregation (delta = last - first)
                data[key + '_cum'] = value
                data[key]=self.AE_RE_comulative_to_static(key,value)
               
            return self.tolowercase(data)#data
        except Exception as e:
            self.logger.insert_Error_APP_log("data not completed ..", e)
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



from time import time
import struct

 
class SPM32:
    #['Time', 'PanelID', 'MeterID', 'Node', 'AV', 'BV', 'CV', 'F', 'C1Ia', 'C1Ib', 'C1Ic', 'C2Ia', 'C2Ib', 'C2Ic', 'C3Ib', 'C3Ic', 'C4Ia', 'C4Ib', 'C4Ic', 'C1Pa', 'C1Pb', 'C1Pc', 'C2Pa', 'C2Pb', 'C2Pc', 'C3Pa', 'C3Pb', 'C3Pc', 'C4Pa', 'C4Pb', 'C4Pc', 'C1Qa', 'C1Qb', 'C1Qc', 'C2Qa', 'C2Qb', 'C2Qc', 'C3Qa', 'C3Qb', 'C3Qc', 'C4Qa', 'C4Qb', 'C4Qc', 'C1PFa', 'C1PFb', 'C1PFc', 'C2PFa', 'C2PFb', 'C2PFc', 'C3PFa', 'C3PFb', 'C3PFc', 'C4PFa', 'C4PFb', 'C4PFc', 'C1Sa', 'C1Sb', 'C1Sc', 'C2Sa', 'C2Sb', 'C2Sc', 'C3Sa', 'C3Sb', 'C3Sc', 'C4Sa', 'C4Sb', 'C4Sc', 'C1AEa', 'C1AEb', 'C1AEc', 'C2AEa', 'C2AEb', 'C2AEc', 'C3AEa', 'C3AEb', 'C3AEc', 'C4AEa', 'C4AEb', 'C4AEc', 'C1REa', 'C1REb', 'C1REc', 'C2REa', 'C2REb', 'C2REc', 'C3REa', 'C3REb', 'C3REc', 'C4REa', 'C4REb', 'C4REc']
    LOG_HEADER = ['sendingDate', 'level', 'PanelID', 'MeterID', 'Node', 'Time']          
    
    
    
   
    READING_PAYLOADS=[{"address":0,"count": 66}]
    

    '''
       
        
    ''' 

    values=[
            {"key":"AV","remark":100,"position":1,"length":1},# *PT   *********
            {"key":"BV","remark":100,"position":2,"length":1},# *PT   *********
            {"key":"CV","remark":100,"position":3,"length":1},# *PT   *********
            {"key":"Vab","remark":100,"position":4,"length":1},# *PT   *********
            {"key":"Vbc","remark":100,"position":5,"length":1},# *PT   *********
            {"key":"Vca","remark":100,"position":6,"length":1},# *PT   *********
            {"key":"F","remark":100,"position":25,"length":1},
    
            {"key":"C1I","remark":1000,"position":7,"length":1}, # *CT   *********
            {"key":"C1V","remark":100,"position":1,"length":1},# *PT   *********
            {"key":"C1P","remark":10000,"position":16,"length":1,"type":"h"},
            {"key":"C1Q","remark":10000,"position":19,"length":1,"type":"h"},
            {"key":"C1S","remark":10000,"position":47,"length":1},
            {"key":"C1PF","remark":1000,"position":22,"length":1,"type":"h"},
            {"key":"C1AE","remark":1,"position":-1,"length":0},######## calculation
            {"key":"C1RE","remark":1,"position":-1,"length":0},######## calculation
            
            {"key":"C2I","remark":1000,"position":8,"length":1},# *CT   *********
            {"key":"C2V","remark":100,"position":2,"length":1},# *PT   *********
            {"key":"C2P","remark":10000,"position":17,"length":1,"type":"h"},
            {"key":"C2Q","remark":10000,"position":20,"length":1,"type":"h"},
            {"key":"C2S","remark":10000,"position":48,"length":1},
            {"key":"C2PF","remark":1000,"position":23,"length":1,"type":"h"},
            {"key":"C2AE","remark":1,"position":-1,"length":0},######## calculation
            {"key":"C2RE","remark":1,"position":-1,"length":0},######## calculation
            
            {"key":"C3I","remark":1000,"position":9,"length":1},# *CT   *********
            {"key":"C3V","remark":100,"position":3,"length":1},# *PT   *********
            {"key":"C3P","remark":10000,"position":18,"length":1,"type":"h"},
            {"key":"C3Q","remark":10000,"position":21,"length":1,"type":"h"},
            {"key":"C3S","remark":10000,"position":49,"length":1},
            {"key":"C3PF","remark":1000,"position":24,"length":1,"type":"h"},
            {"key":"C3AE","remark":1,"position":-1,"length":0},######## calculation
            {"key":"C3RE","remark":1,"position":-1,"length":0},######## calculation
            
            {"key":"TI","remark":1,"position":-1,"length":0},######## calculation   
            {"key":"V","remark":100,"position":43,"length":1},
            {"key":"TP","remark":10000,"position":11,"length":2,"type":"i"}, # *PT*CT   *********
            {"key":"TQ","remark":10000,"position":13,"length":2,"type":"i"}, # *PT*CT   *********
            {"key":"TS","remark":10000,"position":50,"length":2},
            {"key":"TPF","remark":1000,"position":15,"length":1,"type":"h"},
            {"key":"TAE","remark":10,"position":26,"length":2}, 
            {"key":"TRE","remark":10,"position":28,"length":2},
            {"key":"TSE","remark":10,"position":52,"length":2},
            
 
            {"key":"NI","remark":1000,"position":10,"length":1}, # *CT   *********
            {"key":"Iavg","remark":1000,"position":45,"length":1},
            {"key":"Iubr","remark":1000,"position":46,"length":1},
            {"key":"Vph","remark":100,"position":44,"length":1},
            {"key":"Vubr","remark":100,"position":55,"length":1},
            {"key":"Vz","remark":100,"position":57,"length":1},
            {"key":"Vp","remark":100,"position":58,"length":1},
            {"key":"Vn","remark":100,"position":59,"length":1},
            {"key":"C1VG","remark":1,"position":60,"length":1},
            {"key":"C2VG","remark":1,"position":61,"length":1},
            {"key":"C3VG","remark":1,"position":62,"length":1},
            {"key":"C1IG","remark":1,"position":63,"length":1},
            {"key":"C2IG","remark":1,"position":64,"length":1},
            {"key":"C3IG","remark":1,"position":65,"length":1},
            {"key":"CTRatio","remark":1,"position":41,"length":1},
            {"key":"PTRatio","remark":1,"position":42,"length":1}
          
        
            
            ]
  

    

    summingValues={}

    # V  * PTR 
  
    summingValues['TI']= ['C1I','C2I','C3I']
    
    for item in values:
        LOG_HEADER+=[item['key']]	

    
   
    LOG_HEADER+=["version"]
     
    def getSummingValues(self):
        return self.summingValues


 




    DeviceValues={}
    

    def __init__(self,PanelID,MeterID,Node,meter_info) :
        self.lastAE_RE={}
        self.accmAE_RE= {"C1AE":0.0,"C2AE":0.0,"C3AE":0.0,"C1RE":0.0,"C2RE":0.0,"C3RE":0.0,"TAE":0.0,"TRE":0.0}
        self.meter_info=meter_info
        #self.ignore_CTS =  self.meter_info["ignore_CTS"] if "ignore_CTS" in self.meter_info   else []
        self.DeviceValues = {
          "PanelID": PanelID,
          "MeterID": MeterID,
          "Node":  Node
        }
    
    
    

    def getDeviceValues(self):
        self.DeviceValues['time']=int(time()*1000)
        return self.DeviceValues

  
    def getValues(self):
        return self.values


    def decode(self,bytes):
        payload = {}
        
        # PanelID MeterID Node
        payload.update(self.getDeviceValues())

        # all values
        for item in self.getValues():
            if(item['length'] == 0):
                payload[item['key']]=0
            
            elif(item['length'] == 1):
                numbytes = bytes[item["position"]-1].to_bytes(2, 'big')
                #if not "type" in item else item["type"]
                payload[item['key']] = struct.unpack('>h' ,numbytes)[0] /item["remark"]
            elif(item['length'] == 2):
                low_byte = bytes[item["position"]-1].to_bytes(2, 'big')
                high_byte  = bytes[item["position"]].to_bytes(2, 'big')
                #if not "type" in item else item["type"]
                value = struct.unpack('>i' , high_byte+low_byte)[0]
                payload[item['key']] = value /item["remark"]
            payload[item['key']]= abs(payload[item['key']]) # doing abs

        CTRO = self.meter_info["CTRO"] if "CTRO" in self.meter_info else 1
        if (payload["CTRatio"]<=1):
            payload["CTRatio"]=CTRO
        
        payload["TPF"]=round(abs(payload["TPF"]),5)
        payload["C1PF"]=round(abs(payload["C1PF"]),5)
        payload["C2PF"]=round(abs(payload["C2PF"]),5)
        payload["C3PF"]=round(abs(payload["C3PF"]) ,5)   
        ##### PT CT multiplied
        payload["AV" ]=round(payload["AV" ]*payload["PTRatio"],5)       # *PT   *********
        payload["BV" ]=round(payload["BV" ]*payload["PTRatio"],5)       # *PT   *********
        payload["CV" ]=round(payload["CV" ]*payload["PTRatio"],5)       # *PT   *********
        payload["Vab"]=round(payload["Vab"]*payload["PTRatio"],5)       # *PT   *********
        payload["Vbc"]=round(payload["Vbc"]*payload["PTRatio"],5)       # *PT   *********
        payload["Vca"]=round(payload["Vca"]*payload["PTRatio"],5)       # *PT   *********
        payload["C1V"]=round(payload["C1V"]*payload["PTRatio"],5)       # *PT   *********
        payload["C2V"]=round(payload["C2V"]*payload["PTRatio"],5)       # *PT   *********
        payload["C3V"]=round(payload["C3V"]*payload["PTRatio"],5)       # *PT   *********
        
        payload["C1I"]=round(payload["C1I"]*payload["CTRatio"],5)       # *CT   *********
        payload["C2I"]=round(payload["C2I"]*payload["CTRatio"],5)       # *CT   *********
        payload["C3I"]=round(payload["C3I"]*payload["CTRatio"],5)       # *CT   *********   
        payload["NI" ]=round(payload["NI" ]*payload["CTRatio"],5)       # *CT   *********
        payload["Iubr" ]=round(payload["Iubr" ]*payload["CTRatio"],5)       # *CT   *********
        payload["Iavg" ]=round(payload["Iavg" ]*payload["CTRatio"],5)       # *CT   *********
        
        
        payload["TP" ]=abs(round(payload["TP" ]*payload["PTRatio"]*payload["CTRatio"],5))       # *PT*CT   *********
        payload["TQ" ]=abs(round(payload["TQ" ]*payload["PTRatio"]*payload["CTRatio"],5))       # *PT*CT   *********
        payload["TS" ]=round(payload["TS" ] * payload["PTRatio"] * payload["CTRatio"] ,5)       # *PT*CT   ****AI*****
        
        
         
        payload["C1P" ]=round(payload["C1P" ]*payload["PTRatio"]*payload["CTRatio"],5)          # *PT*CT   ****AI*****
        payload["C1Q" ]=abs(round(payload["C1Q" ]*payload["PTRatio"]*payload["CTRatio"],5))     # *PT*CT   ****AI*****
        payload["C1S" ]=round(payload["C1S" ]*payload["PTRatio"]*payload["CTRatio"],5)          # *PT*CT   ****AI*****
        
        payload["C2P" ]=round(payload["C2P" ]*payload["PTRatio"]*payload["CTRatio"],5)          # *PT*CT   ****AI*****
        payload["C2Q" ]=abs(round(payload["C2Q" ]*payload["PTRatio"]*payload["CTRatio"],5))     # *PT*CT   ****AI*****
        payload["C2S" ]=round(payload["C2S" ]*payload["PTRatio"]*payload["CTRatio"],5)          # *PT*CT   ****AI*****
           
        payload["C3P" ]=round(payload["C3P" ]*payload["PTRatio"]*payload["CTRatio"],5)          # *PT*CT   ****AI*****
        payload["C3Q" ]=abs(round(payload["C3Q" ]*payload["PTRatio"]*payload["CTRatio"],5))     # *PT*CT   ****AI*****
        payload["C3S" ]=round(payload["C3S" ]*payload["PTRatio"]*payload["CTRatio"],5)          # *PT*CT   ****AI*****
        
        
        
        payload["TAE" ]=round(payload["TAE" ],5)    
        payload["TRE" ]=round(payload["TRE" ],5)    
        payload["TSE" ]=round(payload["TSE" ],5)   

        def aedvd(key,value):
            temp = 0.0 
            if(key in self.lastAE_RE.keys()):
                temp =int(value*1000)-int(self.lastAE_RE[key]*1000)
                temp = round(temp/1000,5)
            self.lastAE_RE[key]=value
            return temp
        tae = aedvd("TAE",payload["TAE" ])
        tre = aedvd("TRE",payload["TRE" ])
      
        
          
        
        #### sumation 
        payload["TI"]=round(payload['C1I']+payload['C2I']+payload['C3I'],5)  

        self.accmAE_RE["C1AE"]+=(tae * payload['C1I']/payload['TI'] if payload['TI'] !=0 else 0)
        self.accmAE_RE["C2AE"]+=(tae * payload['C2I']/payload['TI'] if payload['TI'] !=0 else 0 )
        self.accmAE_RE["C3AE"]+=(tae * payload['C3I']/payload['TI'] if payload['TI'] !=0 else 0)
        payload["C1AE"]=self.accmAE_RE["C1AE"]
        payload["C2AE"]=self.accmAE_RE["C2AE"]
        payload["C3AE"]=self.accmAE_RE["C3AE"]


        self.accmAE_RE["C1RE"]+=(tre * payload['C1I']/payload['TI'] if payload['TI'] !=0 else 0)
        self.accmAE_RE["C2RE"]+=(tre * payload['C2I']/payload['TI'] if payload['TI'] !=0 else 0)
        self.accmAE_RE["C3RE"]+=(tre * payload['C3I']/payload['TI'] if payload['TI'] !=0 else 0)
        payload["C1RE"]=self.accmAE_RE["C1RE"]
        payload["C2RE"]=self.accmAE_RE["C2RE"]
        payload["C3RE"]=self.accmAE_RE["C3RE"]
        
        #print("TAE",tae,"TRE",tre,"C1AE",payload["C1AE"],"C2AE",payload["C2AE"],"C3AE",payload["C3AE"],"C1RE",payload["C1RE"],"C2RE",payload["C2RE"],"C3RE",payload["C3RE"])
             



        #payload['V']=round((payload['AV']*payload['C1I'] +payload['BV']*payload['C2I']+payload['CV']*payload['C3I'] )/payload['TI'] if payload['TI'] !=0 else 0,3  )

        #print(payload)
        return payload
        #return self.doIgnoringCTS(payload)




    oo=-1
    def getsampleData(self):
        a=[
            [23607, 23397, 23468, 40712, 40651, 40696, 2210, 2260, 2131, 4, 10904, 0, 11011, 0, 702, 3773, 3633, 3498, 3600, 3839, 3572, 722, 
             686, 698, 5997, 4213, 0, 4276, 0, 4213, 0, 0, 0, 4276, 0, 0, 0, 0, 0, 0, 200, 1, 23490, 40686, 2200, 32, 5218, 5289, 5002, 15509, 0, 
             6009, 0, 0, 0, 0, 106, 23488, 21, 0, 240, 120, 316, 193, 74, 9797],
            [23594, 23381, 23454, 40698, 40623, 40664, 2209, 2261, 2133, 4, 10927, 0, 10982, 0, 704, 3777, 3643, 3507, 3589, 3827, 3566, 724, 688,
              700, 5995, 4249, 0, 4313, 0, 4249, 0, 0, 0, 4313, 0, 0, 0, 0, 0, 0, 200, 1, 23476, 40661, 2201, 32, 5213, 5286, 5004, 15503, 0, 6062, 
              0, 0, 1, 0, 109, 23474, 24, 0, 240, 120, 316, 193, 74, 9857],
            [23596, 23385, 23451, 40693, 40622, 40676, 2213, 2263, 2136, 4, 10960, 0, 10978, 0, 705, 3790, 3652, 3518, 3589, 3826, 3563, 724, 689, 
             701, 5997, 4286, 0, 4349, 0, 4286, 0, 0, 0, 4349, 0, 0, 0, 0, 0, 0, 200, 1, 23477, 40663, 2204, 32, 5223, 5293, 5010, 15526, 0, 6112, 
             0, 0, 1, 0, 104, 23475, 24, 0, 240, 120, 316, 193, 74, 9917],
            [23603, 23393, 23457, 40701, 40632, 40693, 2221, 2272, 2142, 4, 11041, 0, 10978, 0, 708, 3819, 3681, 3541, 3585, 3831, 3562, 728, 692, 
             704, 6001, 4323, 0, 4386, 0, 4323, 0, 0, 0, 4386, 0, 0, 0, 0, 0, 0, 200, 1, 23484, 40675, 2211, 32, 5242, 5316, 5025, 15583, 0, 6164, 
             0, 0, 1, 0, 101, 23479, 25, 0, 240, 120, 317, 194, 75, 9977],
            [23610, 23402, 23464, 40732, 40664, 40670, 2214, 2268, 2134, 4, 10978, 0, 10988, 0, 705, 3801, 3662, 3515, 3586, 3838, 3564, 726, 689, 
             701, 6000, 4358, 0, 4423, 0, 4358, 0, 0, 0, 4423, 0, 0, 0, 0, 0, 0, 200, 1, 23492, 40688, 2205, 33, 5228, 5308, 5008, 15544, 0, 6217, 
             0, 0, 1, 0, 118, 23487, 24, 0, 240, 120, 317, 194, 74, 10037]
            ]

        self.oo+=1
        if self.oo >= len(a):
            self.oo =0
        return a[self.oo]

                
        


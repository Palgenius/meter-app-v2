from time import time
import struct

 
class SPM206:
    def init(self,NUMBEROFCROUPS): 
        self.NUMBEROFCROUPS=NUMBEROFCROUPS
        self.NUMBEROFCT=self.NUMBEROFCROUPS*6

        self.LOG_HEADER = ['sendingDate', 'level', 'PanelID', 'MeterID', 'Node', 'Time',"AV","BV","CV","V","F", "Ia_input","Ib_input","Ic_input", "TI_input","NI","IUR",                                                 
        "ILG","NV","CTRO","Pa_input","Pb_input","Pc_input","TP_input","Qa_input","Qb_input","Qc_input","TQ_input","PFa_input","PFb_input","PFc_input","TPF_input",
        "Sa_input","Sb_input","Sc_input","TS_input","VTHDa","VTHDb","VTHDc","ITHDa","ITHDb","ITHDc","TAE_input","TRE_input"]

        #for i in range(1,self.NUMBEROFCT+1):
        for i in range(1,43):
            self.LOG_HEADER +=[f"C{i}I",f"C{i}V",f"C{i}P",f"C{i}Q",f"C{i}S",f"C{i}PF",f"C{i}ITHD",f"C{i}AE",f"C{i}RE"] 

        for i in ['a','b','c']:
            self.LOG_HEADER +=[f'I{i}', f'P{i}', f'Q{i}', f'S{i}', f'PF{i}', f'AE{i}', f'RE{i}'] 
        self.LOG_HEADER += ['TI', 'TP', 'TQ','TS','TPF','TAE', 'TRE' ,"version"]

    



        self.READING_PAYLOADS=[{'address': 0, 'count': 69}] #69
        startregster= 200
        allregesters = 89*self.NUMBEROFCROUPS
        divider=65
        ranger =allregesters//divider
        remaining=allregesters-(ranger*divider)
        #69 71 
        count=0
        for i in range(ranger): 
            _divider = divider +1 if i %2 == 0 else divider -1
            self.READING_PAYLOADS+= [{"address": startregster+count,"count": _divider }]
            count+=_divider

        remaining=allregesters-count
        if (remaining>0 ):
            self.READING_PAYLOADS+= [{"address": startregster+count,"count": remaining}]
        elif(remaining<0):
            self.READING_PAYLOADS[-1]['count']+=remaining
        #for i in range(self.NUMBEROFCROUPS):    #801  
        #    self.READING_PAYLOADS+= [{"address": 200+i*89,"count": 89}]          
            #self.READING_PAYLOADS+= [{"address": 200+i*89,"count": 50}]
            #self.READING_PAYLOADS+= [{"address": 50+200+i*89,"count": 39}]
        
        #1500 ->1720   220
        #4 54  9
        #3 36  6
        #2 24  4
        #1 12  2
        #SC/2
        #maxspecturm=4
        if (self.NUMBEROFCROUPS/2<=1):
            self.READING_PAYLOADS+= [{"address": 1500,"count": 55}]
        #    maxspecturm=1
        elif (self.NUMBEROFCROUPS/2<=2):
            self.READING_PAYLOADS+= [{"address": 1500,"count": 55}]
            self.READING_PAYLOADS+= [{"address": 1500+55,"count": 57}]
        #    maxspecturm=2
        elif (self.NUMBEROFCROUPS/2<=3):
            self.READING_PAYLOADS+= [{"address": 1500,"count": 51}]
            self.READING_PAYLOADS+= [{"address": 1500+51,"count": 55}]
            self.READING_PAYLOADS+= [{"address": 1500+51+55,"count": 59}]
        #    maxspecturm=3
        else:
            self.READING_PAYLOADS+= [{"address": 1500,"count": 51}]
            self.READING_PAYLOADS+= [{"address": 1500+51,"count": 55}]
            self.READING_PAYLOADS+= [{"address": 1500+51+55,"count": 59}]
            self.READING_PAYLOADS+= [{"address": 1500+51+55+59,"count": 55}]


      #  for i in range(maxspecturm):                
      #      self.READING_PAYLOADS+= [{"address": 1500+i*55,"count": 55}]

        self.values=[
            {"key":"AV","remark":100,"position":1,"length":1},
            {"key":"BV","remark":100,"position":2,"length":1},
            {"key":"CV","remark":100,"position":3,"length":1},
            {"key":"V","remark":1,"position":-1,"length":0},#calcolated
            {"key":"F","remark":100,"position":38,"length":1},

            {"key":"Ia_input","remark":1000,"position":4,"length":1},
            {"key":"Ib_input","remark":1000,"position":5,"length":1},
            {"key":"Ic_input","remark":1000,"position":6,"length":1},
            {"key":"TI_input","remark":1,"position":-1,"length":0},#calcolated
            {"key":"NI","remark":1000,"position":7,"length":1},
            {"key":"IUR","remark":10,"position":8,"length":1},#Input current unbalance rate    
            {"key":"ILG","remark":1000,"position":54,"length":1},
            {"key":"NV","remark":100,"position":56,"length":1},
            {"key":"CTRO","remark":1,"position":58,"length":1},


            {"key":"Pa_input","remark":10000,"position":19,"length":1},
            {"key":"Pb_input","remark":10000,"position":20,"length":1},
            {"key":"Pc_input","remark":10000,"position":21,"length":1},
            {"key":"TP_input","remark":10000,"position":22,"length":2},
            {"key":"Qa_input","remark":10000,"position":47,"length":1},
            {"key":"Qb_input","remark":10000,"position":48,"length":1},
            {"key":"Qc_input","remark":10000,"position":49,"length":1},
            {"key":"TQ_input","remark":10000,"position":50,"length":2},
            {"key":"PFa_input","remark":1000,"position":34,"length":1},
            {"key":"PFb_input","remark":1000,"position":35,"length":1},
            {"key":"PFc_input","remark":1000,"position":36,"length":1},
            {"key":"TPF_input","remark":1000,"position":37,"length":1},

            {"key":"Sa_input","remark":1,"position":-1,"length":0},#calcolated
            {"key":"Sb_input","remark":1,"position":-1,"length":0},#calcolated
            {"key":"Sc_input","remark":1,"position":-1,"length":0},#calcolated
            {"key":"TS_input","remark":1,"position":-1,"length":0},#calcolated

            
         
            {"key":"VTHDa","remark":100,"position":41,"length":1},
            {"key":"VTHDb","remark":100,"position":42,"length":1},
            {"key":"VTHDc","remark":100,"position":43,"length":1},
            {"key":"ITHDa","remark":1000,"position":44,"length":1},
            {"key":"ITHDb","remark":1000,"position":45,"length":1},
            {"key":"ITHDc","remark":1000,"position":46,"length":1},

            {"key":"TAE_input","remark":10,"position":39,"length":2},
            {"key":"TRE_input","remark":10,"position":52,"length":2}
            
            ]

        #for i in range(1,self.NUMBEROFCT+1):
        for i in range(1,43):
            #[f"C{i}I",f"C{i}P",f"C{i}Q",f"C{i}ITHD",f"C{i}F",f"C{i}AE",f"C{i}RE",f"C{i}PF"]
            start=69+(14*(i-1))#+(i-1) #56
            start+=(5*((i-1)//6))
            number=i
            self.values+=[
            {"key":f"C{number}I","remark":100,"position":start+1 ,"length":1 if(i<=self.NUMBEROFCT) else 0},
            {"key":f"C{number}V","remark":1,"position":-1,"length":0},#calcolated
            {"key":f"C{number}P","remark":1000,"position":start+5,"length":1  if(i<=self.NUMBEROFCT) else 0},
            {"key":f"C{number}Q","remark":1000,"position":start+9,"length":1  if(i<=self.NUMBEROFCT) else 0},
            {"key":f"C{number}S","remark":1,"position":-1,"length":0},#calcolated
            {"key":f"C{number}PF","remark":1000,"position":start+8,"length":1  if(i<=self.NUMBEROFCT) else 0}, 
            {"key":f"C{number}ITHD","remark":100,"position":start+10,"length":1  if(i<=self.NUMBEROFCT) else 0},
            {"key":f"C{number}AE","remark":10,"position":start+11,"length":2  if(i<=self.NUMBEROFCT) else 0},
            {"key":f"C{number}RE","remark":10,"position":start+13,"length":2  if(i<=self.NUMBEROFCT) else 0}
        
            ]
        
        for i in range(1,self.NUMBEROFCT+2):
        
            start=69+(self.NUMBEROFCROUPS*89)+(4*(i-1))+1
            if(i==1):
                key1="TAE_input"
                key2="TRE_input"
            else:
                key1=f"C{i-1}AE"
                key2=f"C{i-1}RE"

            self.values+=[
            {"key":key1,"remark":100,"position":start,"length":2},
            {"key":key2,"remark":100,"position":start+2,"length":2}
        
            ]

        CTA=[i for i in range(1,self.NUMBEROFCT+1,3)] 
        CTB=[i for i in range(2,self.NUMBEROFCT+1,3)]
        CTC=[i for i in range(3,self.NUMBEROFCT+1,3)]
        self.summingValues={
            'Ia' :{"opr":"sum","val":"I","range": CTA },
            'Pa' :{"opr":"sum","val":"P","range": CTA },
            'Qa' :{"opr":"sum","val":"Q","range": CTA },
            'Sa' :{"opr":"sum","val":"S","range": CTA },
            'PFa':{"opr":"avg","val":"PF","range":CTA , "need":"I" },
            'AEa':{"opr":"sum","val":"AE","range":CTA},
            'REa':{"opr":"sum","val":"RE","range":CTA},

            'Ib' :{"opr":"sum","val":"I","range": CTB },
            'Pb' :{"opr":"sum","val":"P","range": CTB },
            'Qb' :{"opr":"sum","val":"Q","range": CTB },
            'Sb' :{"opr":"sum","val":"S","range": CTB },
            'PFb':{"opr":"avg","val":"PF","range":CTB , "need":"I" },
            'AEb':{"opr":"sum","val":"AE","range":CTB},
            'REb':{"opr":"sum","val":"RE","range":CTB},

            'Ic': {"opr":"sum","val":"I","range": CTC },
            'Pc': {"opr":"sum","val":"P","range": CTC },
            'Qc': {"opr":"sum","val":"Q","range": CTC },
            'Sc': {"opr":"sum","val":"S","range": CTC },
            'PFc':{"opr":"avg","val":"PF","range":CTC , "need":"I" },
            'AEc':{"opr":"sum","val":"AE","range":CTC},
            'REc':{"opr":"sum","val":"RE","range":CTC},

            'TI' : {"opr":"sum","val":"I","range":range(1,self.NUMBEROFCT+1) },
            'TP' : {"opr":"sum","val":"P","range":range(1,self.NUMBEROFCT+1) },
            'TQ' : {"opr":"sum","val":"Q","range":range(1,self.NUMBEROFCT+1) },
            'TS' : {"opr":"sum","val":"S","range":range(1,self.NUMBEROFCT+1) },
            'TPF': {"opr":"avg","val":"PF","range":range(1,self.NUMBEROFCT+1), "need":"I" },
            'TAE' :{"opr":"sum","val":"AE","range":range(1,self.NUMBEROFCT+1)},
            'TRE' :{"opr":"sum","val":"RE","range":range(1,self.NUMBEROFCT+1)},
            
        
            }    
        
    def getSummingValues(self):
        return self.summingValues
    
    DeviceValues={}
    

    def __init__(self,PanelID,MeterID,Node,meter_info) :
        
        self.meter_info=meter_info
        self.DeviceValues = {
          "PanelID": PanelID,
          "MeterID": MeterID,
          "Node":  Node
        }
        self.init(meter_info["numberOfGroups"] if "numberOfGroups" in meter_info else 7 )


     

    def getDeviceValues(self):
        self.DeviceValues['time']=int(time()*1000)
        return self.DeviceValues

    def getValues(self):
        return self.values


    def decode(self,bytes):
        payload = {}
        #print("dsfdsf>>>>>>>>>>>>>",self.READING_PAYLOADS)
        # PanelID MeterID Node
        payload.update(self.getDeviceValues())
        #print(self.getValues(),len(bytes))
        # all values
        for item in self.getValues():
        
            if(item['length'] == 0):
                payload[item['key']]=0
            elif(item['length'] == 1):
                numbytes = bytes[item["position"]-1].to_bytes(2, 'big')
                payload[item['key']] = struct.unpack('>h',numbytes)[0] / item["remark"]
            elif(item['length'] == 2):
                low_byte = bytes[item["position"]-1].to_bytes(2, 'big')
                high_byte = bytes[item["position"]].to_bytes(2, 'big')
                value = struct.unpack('>i', high_byte+low_byte)[0]
                payload[item['key']] = value /item["remark"]
            payload[item['key']]=abs(payload[item['key']])
        #payload.update(self.getstaticValues())
        # mutiplying the CT ratio with input values
        CTRO = self.meter_info["CTRO"] if "CTRO" in self.meter_info else 50

        # input current =register’s value × coefficient×CT ratio  AI BI CI ITHDa ITHDb ITHDc
        payload["Ia_input"]=round(payload["Ia_input"]*CTRO,4)
        payload["Ib_input"]=round(payload["Ib_input"]*CTRO,4)
        payload["Ic_input"]=round(payload["Ic_input"]*CTRO,4)
        payload["TI_input"]=payload["Ia_input"]+payload["Ib_input"]+payload["Ic_input"]

        payload["ITHDa"]=round(payload["ITHDa"]*CTRO,4)
        payload["ITHDb"]=round(payload["ITHDb"]*CTRO,4)
        payload["ITHDc"]=round(payload["ITHDc"]*CTRO,4)
        #payload["TITHD"]=payload["ITHDa"]+payload["ITHDb"]+payload["ITHDc"]
        #Input phase active power =register’s value ×coefficient×CT ratio   Pa Pb Pc
        payload["Pa_input"]=round(payload["Pa_input"]*CTRO,4)
        payload["Pb_input"]=round(payload["Pb_input"]*CTRO,4)
        payload["Pc_input"]=round(payload["Pc_input"]*CTRO,4)
        #Input three-phase total  active power =register’s value ×coefficient×CT ratio TP
        payload["TP_input"]=round(payload["TP_input"]*CTRO,4)

        #Input phase reactive power =register’s value ×coefficient×CT ratio  Qa Qb Qc
        payload["Qa_input"]=round(payload["Qa_input"]*CTRO,4)
        payload["Qb_input"]=round( payload["Qb_input"]*CTRO,4)
        payload["Qc_input"]=round(payload["Qc_input"]*CTRO,4)
        #Input three-phase total  reactive power =register’s value ×coefficient×CT ratio TQ
        payload["TQ_input"]=round(payload["TQ_input"]*CTRO,4)
        #Input total active energy  =register’s value ×coefficient×CT ratio TQ
        payload["TAE_input"]=round(payload["TAE_input"]*CTRO,4)
        #Input total reactive energy  =register’s value ×coefficient×CT ratio TQ
        payload["TRE_input"]=round(payload["TRE_input"]*CTRO,4)

        for i in range(1,self.NUMBEROFCT+1):
            payload[f"C{i}S"]=round(payload[f"C{i}P"]/payload[f"C{i}PF"] if payload[f"C{i}PF"] != 0 else 0,4)

        payload["Sa_input"]=round(payload["Pa_input"]/payload["PFa_input"] if payload["PFa_input"] != 0 else 0,4)
        payload["Sb_input"]=round(payload["Pb_input"]/payload["PFb_input"] if payload["PFb_input"] != 0 else 0,4)
        payload["Sc_input"]=round(payload["Pc_input"]/payload["PFc_input"] if payload["PFc_input"] != 0 else 0,4)
        payload["TS_input"]=round(payload["TP_input"]/payload["TPF_input"] if payload["TPF_input"] != 0 else 0,4)
        
        

     
            
            


        for key,ops in self.getSummingValues().items():
               
            if(ops['opr']=='sum'):
                payload[key] = round(sum([payload[f'C{k}{ops["val"]}'] if f'C{k}{ops["val"]}' in payload else 0 for k in ops["range"]]), 3)
            elif(ops['opr']=='avg'):
                ti =sum([payload[f'C{k}{ops["need"]}'] if f'C{k}{ops["need"]}' in payload and payload[f'C{k}{ops["val"]}'] !=0  else 0 for k in ops["range"]])
                payload[key] = round( sum([payload[f'C{k}{ops["val"]}']*payload[f'C{k}{ops["need"]}'] 
                if f'C{k}{ops["val"]}' in payload  and f'C{k}{ops["need"]}' in payload else 0
                for k in ops["range"]])/ ti if ti != 0 else ti , 3)

        for i in range(1,self.NUMBEROFCT+1,3):
            payload[f'C{i}V']=payload['AV']
        for i in range(2,self.NUMBEROFCT+1,3):
            payload[f'C{i}V']=payload['BV']
        for i in range(3,self.NUMBEROFCT+1,3):
            payload[f'C{i}V']=payload['CV']
        payload['V']=round((payload['AV']*payload['Ia'] +payload['BV']*payload['Ib']+payload['CV']*payload['Ic'] )/payload['TI'] if payload['TI'] != 0 else (payload['AV'] +payload['BV']+payload['CV'])/3 ,3 )
        #print(payload)
        return payload

    def getsampleData(self):
        #56 >> 59
        gen= [16750, 21422, 21488, 914, 831, 835, 0, 90, 1389, 1515, 1432, 0, 923, 838, 841, 1307, 1147, 1188, 1302, 1430, 1612, 4345, 0, 1325, 1449, 
        1623, 4398, 0, 1880, 1928, 2390, 6047, 0, 850, 803, 898, 851, 4999, 12194, 0, 12, 12, 11, 18, 42, 32, 799, 1056, 786, 2642, 0, 7667, 0, 0, 0, 
        0, 107, 1, 256      ,0,0,0,0,0  ,0,0,0,0,0]
       
        cb=[ #1
        489, 653, 488, 646, 565, 564, 693, 690, 593, 0, 31734, 0, 36574, 0, 0, 67, 0, 66, 0, 0, 95, 0, 0, 0, 2633, 0, 567, 0, 64, 75, 64, 72, 111, 
        110, 125, 808, 43, 0, 5582, 0, 2479, 0, 0, 67, 0, 65, 0, 0, 67, 0, 0, 0, 1929, 0, 718, 0, 248, 398, 248, 397, 409, 408, 541, 771, 284, 0, 24394, 
        0, 23149, 0, 187, 1598, 187, 888, 343, 342, 1909, 854, 180, 0, 19440, 0, 13365, 0      ,0,0,0,0,0]+[
        #2
        0, 117, 0, 111, 0, 0, 127, 0, 0, 0, 3346, 0,1290, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 137, 0, 130, 0, 0, 148, 0, 0, 0, 4941, 0, 
        2173, 0, 0, 78, 0, 76, 0, 0, 89, 0, 0, 0, 2426, 0, 485, 0, 58, 74, 58, 63, 95, 94, 100, 765, 25, 0, 4721, 0, 1600, 0, 0, 65, 0, 63, 0, 0, 73, 
        0, 0, 0, 2295, 0, 1096, 0            ,0,0,0,0,0]+[
        #3
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 36, 237, 36, 211, 41, 41, 465, 538, 6, 0, 2407, 0,228, 0, 0, 453, 0, 105, 0, 0, 228, 0, 0, 0, 1, 
        0, 0, 0, 0, 759, 0, 735, 0, 0, 833, 0, 0, 0, 19480, 0, 8336, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 
        0, 0, 0                ,0,0,0,0,0]+[
        #4    
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 495, 0, 150, 0, 0, 207, 0, 0, 0, 17, 0, 40, 0, 75, 126, 72,106, 39, 33, 61, 242, 109, 0, 2055, 
        0, 5706, 0, 656, 759, 664, 742, 956, 974, 1111, 870, 534, 34, 21457, 0, 14775, 0, 812, 923, 823, 915, 1507, 1531, 1730, 866, 865, 26, 44063, 
        0, 25170, 0, 832, 936, 839, 915, 1652, 1671, 1850, 924, 671, 31, 39721, 0, 20204, 0       ,0,0,0,0,0]+[
        #5
        1260, 1496, 1264, 1408, 1821, 1836, 2094,863, 1059, 35, 38396, 0, 25813, 0, 1136, 1405, 1146, 1306, 1828, 1857, 2217, 751, 1598, 43, 34766, 
        0, 38051, 0, 1125, 1383, 1131, 1292, 2064, 2079, 2463, 854, 1256, 41, 40140, 0, 32444, 0, 835, 1436, 837, 1024, 1050, 1057, 1349, 751, 921, 31, 
        12719, 0, 13897, 0, 911, 1536, 916, 1144, 1547, 1557, 2029, 792, 1189, 28, 19772, 0, 18504, 0, 1002, 1457, 1004, 1125, 1867, 1872, 2195, 867, 
        1065, 30, 24513, 0, 17135, 0       ,0,0,0,0,0]+[
        #6
        164, 1552, 164, 1422, 275, 275, 2026, 1000, 5, 0, 9458, 0, 1180, 0, 0, 3319, 0, 1132, 0, 0, 1837,0, 0, 0, 1062, 0, 1096, 0, 0, 3180, 0, 
        1108, 0, 0, 2188, 0, 0, 0, 1326, 0, 739, 0, 1152, 1499, 1160, 1464, 1750, 1763, 2272, 907, 806, 43, 57887, 0, 28615, 0, 917, 1164, 928, 1130, 
        1647, 1666, 2087, 838, 1067, 45, 49884, 0, 37177, 0, 961, 1210, 971, 1184, 1967, 1983, 2457, 952, 629, 48, 60876, 0, 23247, 0        ,0,0,0,0,0]+ [
        #7
        164, 1552, 164, 1422, 275, 275, 2026, 1000, 5, 0, 9458, 0, 1180, 0, 0, 3319, 0, 1132, 0, 0, 1837,0, 0, 0, 1062, 0, 1096, 0, 0, 3180, 0, 
        1108, 0, 0, 2188, 0, 0, 0, 1326, 0, 739, 0, 1152, 1499, 1160, 1464, 1750, 1763, 2272, 907, 806, 43, 57887, 0, 28615, 0, 917, 1164, 928, 1130, 
        1647, 1666, 2087, 838, 1067, 45, 49884, 0, 37177, 0, 961, 1210, 971, 1184, 1967, 1983, 2457, 952, 629, 48, 60876, 0, 23247, 0        ,0,0,0,0,0]+ [
        #8
        164, 1552, 164, 1422, 275, 275, 2026, 1000, 5, 0, 9458, 0, 1180, 0, 0, 3319, 0, 1132, 0, 0, 1837,0, 0, 0, 1062, 0, 1096, 0, 0, 3180, 0, 
        1108, 0, 0, 2188, 0, 0, 0, 1326, 0, 739, 0, 1152, 1499, 1160, 1464, 1750, 1763, 2272, 907, 806, 43, 57887, 0, 28615, 0, 917, 1164, 928, 1130, 
        1647, 1666, 2087, 838, 1067, 45, 49884, 0, 37177, 0, 961, 1210, 971, 1184, 1967, 1983, 2457, 952, 629, 48, 60876, 0, 23247, 0        ,0,0,0,0,0]+ [
        #9
        0,0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 80, 159, 80, 158, 89, 88, 141, 521, 146, 0, 7768, 0, 16862, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 
        0, 0, 29, 521, 28, 179, 30, 27, 86, 620, 21, 0, 1743, 0, 1760, 0, 0, 643, 0, 616, 0, 0, 1374, 0, 0, 0, 7550, 0, 829, 0, 0, 502, 44, 490, 0, 34, 
        404, 0, 0, 0, 1527, 0, 3853, 0        ,0,0,0,0,0]
        dd=[] 
        for i in range(55):
            dd+=[1, 256,0,0]
       
        return gen+cb+dd   
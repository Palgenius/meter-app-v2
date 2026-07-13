

class Format:
 
    def __init__(self,meterName):
        name = meterName.lower()
        if name in ('smp20', 'spm20'):
            from .SMP20Format import SMP20
            self.format =SMP20
        elif name == 'pmac202':
            from .PMAC202Format import PMAC202
            self.format =PMAC202
        elif name == 'pmac211':
            from .PMAC211Format import PMAC211
            self.format =PMAC211
        elif name in ('spm206', 'smp206', 'spm206ct42', 'smp206ct42'):
            from .SPM206CT42Format import SPM206
            self.format =SPM206
        elif name in ('spm206ct54', 'smp206ct54'):
            from .SPM206CT54Format import SPM206
            self.format =SPM206
        elif name in ('spm32', 'smp32'):
            from .SPM32Format import SPM32
            self.format =SPM32
        elif name in ('kitty', 'kitt'):
            from .KittFormat import KITT
            self.format =KITT
        else:
            raise ValueError(f"Unknown meter type: '{meterName}'")
    def getInstance(self,PanelID,MeterID,Node,meter_info):
        return self.format(PanelID,MeterID,Node,meter_info)

        

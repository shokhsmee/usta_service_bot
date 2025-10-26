

from aiogram.fsm.state import StatesGroup, State

# ---- States ----
class Reg(StatesGroup):
    Phone = State()
    Viloyat = State()      # NEW: select state
    Tuman = State()
    Location = State()
    FullName = State()     # NEW: enter full name

class Work(StatesGroup):
    Amount = State()
    ExpType = State()
    ExpAmount = State()   
    ExpNote = State()
    
    PartsPick = State()    
    PartsQty  = State()    
    PartsPrice = State()   

    Photo = State()
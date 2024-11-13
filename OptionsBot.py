import time
from datetime import datetime
from ib_insync import *
from apscheduler.schedulers.background import BackgroundScheduler
import asyncio

#Bot Logic
class Bot:
    ib = None
    def __init__(self):
        #connect to IB on init
        print("Connecting to IB ...")
        self.ib = IB()
        self.ib.connect("127.0.0.1",7497,1)
        print("Successfully connected to IB")

        #get porfolio data
        self.positions = self.ib.positions()
        print("Current Portfolio:")
        for position in self.positions:
            option = Option(
                symbol=position.contract.symbol,  # The underlying symbol
                lastTradeDateOrContractMonth=position.contract.lastTradeDateOrContractMonth,  # Expiration date
                strike=position.contract.strike,  # Strike price
                right=position.contract.right,  # 'C' for call, 'P' for put
                exchange="SMART"  # Exchange where the option is traded
            )
            self.ib.qualifyContracts(option)
            print(f"Created Option: {option}")
            '''print(f"Symbol: {option.symbol}, "
              f"Type: {position.contract.secType}, "
              f"Quantity: {position.position}, "
              f"Strike: {option.strike}, "
              f"Expiry: {option.lastTradeDateOrContractMonth}, "
              f"Right: {option.right}, "
              f"Right: {option.}")'''
            self.get_option_delta(option)
        # Create SPY Contract
        self.underlying = Stock('SPY', 'SMART', 'USD')
        self.ib.qualifyContracts(self.underlying)


        print("Backfilling data to catchup ...")
        # Request Streaming bars
        self.data = self.ib.reqHistoricalData(self.underlying,
            endDateTime='',
            durationStr='2 D',
            barSizeSetting='1 min',
            whatToShow='TRADES',
            useRTH=False,
            keepUpToDate=True)
        if self.data:
            print(f"Latest Close Price: {self.data[-1].close}")
        #Local vars
        self.in_trade = False

        #Get current options chains
        self.chains = self.ib.reqSecDefOptParams(self.underlying.symbol, '', self.underlying.secType, self.underlying.conId)
        #for chain in self.chains:
            #print(chain)

        #request real time market data
        #self.ib.reqRealTimeBars(0,contract,5, "TRADES",0,[])
        #Run forever
        self.ib.run
    #pass real time  bar data back to bot
    def on_bar_update(self, reqId, time, open_, high, low, close,volume, wap, count):
        print(reqId)

    def get_option_delta(self, contract):
        # Request market data for option contract including Greeks
        ticker = self.ib.reqMktData(contract, snapshot=False, regulatorySnapshot=False)

        # Wait for the market data to be updated
        self.ib.sleep(2)  # Adjust sleep time as needed for data to arrive
        
        # Access the delta from the market data
        if ticker:
            delta = ticker.delta
            print(f"Option: {contract.symbol}, Delta: {delta}")

#start bot
bot = Bot()
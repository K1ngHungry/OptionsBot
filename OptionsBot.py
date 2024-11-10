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
            print(f"Symbol: {position.contract.symbol}, "
                    f"Type: {position.contract.secType}, "
                    f"Quantity: {position.position}, "
                    f"Average Cost: {position.avgCost}")

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
        for chain in self.chains:
            print(chain)
        #print(self.chains[0])

        #request real time market data
        #self.ib.reqRealTimeBars(0,contract,5, "TRADES",0,[])
        #Run forever
        self.ib.run
    #pass real time  bar data back to bot
    def on_bar_update(self, reqId, time, open_, high, low, close,volume, wap, count):
        print(reqId)

    def get_option_delta(self, contract):
        # Request market data for option contract including Greeks
        market_data = self.ib.reqMktData(contract, genericTickList="100", snapshot=False, regulatorySnapshot=False)

        # Wait for the market data to be updated
        self.ib.sleep(2)  # Adjust sleep time as needed for data to arrive
        
        # Access the delta from the market data
        if market_data:
            delta = market_data.delta
            print(f"Option: {contract.symbol}, Delta: {delta}")

#start bot
bot = Bot()
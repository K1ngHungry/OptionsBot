from ib_insync import *
import numpy as np
from typing import List, Tuple, Set, Dict
import pandas as pd

class DeltaHedger:
    def __init__(self, ib: IB, underlying_symbol: str, delta_threshold: float = 0.02):
            """
            Initialize with more granular restrictions
            """
            self.ib = ib
            self.underlying_symbol = underlying_symbol
            self.delta_threshold = delta_threshold
            self.stock = Stock(underlying_symbol, 'SMART', 'USD')
            
            # Restricted combinations stored as tuples of (strike, expiration, type)
            # None in any position means "any value is restricted"
            self.restricted_combinations = set()
        
    def add_restriction(self, strike: float = None, expiration: str = None, option_type: str = None):
        """
        Add a specific restriction combination
        Example usages:
        - add_restriction(strike=100, expiration='20240119', option_type='P')  # No puts at strike 100 on this date
        - add_restriction(strike=100, expiration='20240119')  # No options at all at strike 100 on this date
        - add_restriction(strike=100)  # No options at all at strike 100
        """
        self.restricted_combinations.add((strike, expiration, option_type))
        
    def is_allowed_option(self, strike: float, expiration: str, option_type: str) -> bool:
        """
        Check if an option is allowed based on more granular restrictions
        """
        for restricted_strike, restricted_expiration, restricted_type in self.restricted_combinations:
            # Check if this combination matches any restriction
            strike_match = restricted_strike is None or strike == restricted_strike
            expiration_match = restricted_expiration is None or expiration == restricted_expiration
            type_match = restricted_type is None or option_type == restricted_type
            
            if strike_match and expiration_match and type_match:
                return False
                
        return True
        
    def get_current_positions(self) -> Dict[Contract, dict]:
        """Get current portfolio positions with their greeks and tradability"""
        portfolio = self.ib.portfolio()
        positions = {}
        
        for pos in portfolio:
            if pos.contract.symbol != self.underlying_symbol:
                continue
                
            contract = pos.contract
            quantity = pos.position
            
            # Check if this position can be traded under competition rules
            tradable = True
            if contract.secType == 'OPT':
                if not self.is_allowed_option(
                    float(contract.strike),
                    contract.lastTradeDateOrContractMonth,
                    contract.right
                ):
                    tradable = False
            
            # Get current greeks
            tickers = self.ib.reqTickers(contract)
            if tickers and tickers[0].modelGreeks:
                greeks = tickers[0].modelGreeks
                positions[contract] = {
                    'quantity': quantity,
                    'delta': greeks.delta * quantity,
                    'gamma': greeks.gamma * quantity,
                    'tradable': tradable
                }
            
        return positions

    def get_options_chain(self) -> pd.DataFrame:
            """Get available options and their Greeks, excluding restricted options"""
            chains = self.ib.reqSecDefOptParams(self.stock.symbol, '', self.stock.secType, self.stock.conId)
            chain = next(c for c in chains if c.exchange == 'SMART')
            
            strikes = chain.strikes
            expirations = chain.expirations
            
            options_data = []
            
            for expiration in expirations:
                for strike in strikes:
                    # Try both calls and puts if they're allowed
                    for option_type in ['C', 'P']:
                        if self.is_allowed_option(strike, expiration, option_type):
                            opt = Option(self.stock.symbol, expiration, strike, option_type, 'SMART')
                            self._add_option_to_chain(opt, strike, expiration, options_data)
            
            return pd.DataFrame(options_data)

    def find_optimal_portfolio_adjustment(self, current_delta: float) -> List[Tuple[Contract, int]]:
        """
        Find the optimal combination of position adjustments to minimize delta
        Returns list of (contract, quantity_change) tuples
        """
        # Get current positions and available options
        current_positions = self.get_current_positions()
        tradable_positions = {k: v for k, v in current_positions.items() 
                            if v['tradable']}
        
        available_options = self.get_options_chain()
        
        # Combine existing positions and potential new positions for optimization
        all_possibilities = []
        
        # Add possible adjustments to existing positions
        for contract, pos_info in tradable_positions.items():
            current_qty = pos_info['quantity']
            delta_per_unit = pos_info['delta'] / current_qty
            
            # Consider reducing position
            all_possibilities.append({
                'contract': contract,
                'action': 'REDUCE',
                'max_quantity': abs(current_qty),
                'delta_impact_per_unit': -delta_per_unit,  # Negative because we're reducing
                'gamma_impact_per_unit': -pos_info['gamma'] / current_qty
            })
        
        # Add potential new positions from options chain
        for _, row in available_options.iterrows():
            all_possibilities.append({
                'contract': row['contract'],
                'action': 'NEW',
                'max_quantity': 100,  # Reasonable limit for new positions
                'delta_impact_per_unit': row['delta'],
                'gamma_impact_per_unit': row['gamma']
            })
        
        # Find optimal combination using a greedy approach
        target_delta = -current_delta
        adjustments = []
        remaining_delta = target_delta
        
        while abs(remaining_delta) > self.delta_threshold and all_possibilities:
            best_adjustment = None
            best_score = float('inf')
            best_quantity = 0
            
            for pos in all_possibilities:
                # Calculate how many contracts we'd need
                needed_delta = remaining_delta
                quantity = min(
                    abs(int(needed_delta / pos['delta_impact_per_unit'])),
                    pos['max_quantity']
                )
                
                if quantity == 0:
                    continue
                
                # Score this adjustment based on:
                # 1. How close it gets us to target delta
                # 2. Gamma impact
                # 3. Number of contracts needed
                delta_after = remaining_delta - (quantity * pos['delta_impact_per_unit'])
                gamma_impact = abs(quantity * pos['gamma_impact_per_unit'])
                
                score = (
                    abs(delta_after) * 2 +  # Weight for delta improvement
                    gamma_impact * 3 +      # Weight for gamma impact
                    quantity * 0.1          # Small weight for number of contracts
                )
                
                if score < best_score:
                    best_score = score
                    best_adjustment = pos
                    best_quantity = quantity
            
            if best_adjustment is None:
                break
                
            # Add the best adjustment to our list
            adjustments.append((
                best_adjustment['contract'],
                best_quantity if best_adjustment['action'] == 'NEW' else -best_quantity
            ))
            
            # Update remaining delta
            remaining_delta -= best_quantity * best_adjustment['delta_impact_per_unit']
            
            # Remove or update the used adjustment
            if best_adjustment['action'] == 'REDUCE':
                best_adjustment['max_quantity'] -= best_quantity
                if best_adjustment['max_quantity'] <= 0:
                    all_possibilities.remove(best_adjustment)
            else:
                all_possibilities.remove(best_adjustment)
        
        return adjustments

    def execute_adjustments(self, adjustments: List[Tuple[Contract, int]]):
        """Execute the specified portfolio adjustments"""
        for contract, quantity in adjustments:
            action = 'BUY' if quantity > 0 else 'SELL'
            order = MarketOrder(action, abs(quantity))
            trade = self.ib.placeOrder(contract, order)
            
            while not trade.isDone():
                self.ib.sleep(1)
            
            print(f"Executed {action} {abs(quantity)} of {contract.localSymbol}")

    def monitor_and_hedge(self, check_interval: int = 60):
        """Monitor portfolio and make adjustments as needed"""
        while True:
            # Calculate current portfolio delta
            positions = self.get_current_positions()
            total_delta = sum(pos['delta'] for pos in positions.values())
            
            print(f"Current portfolio delta: {total_delta:.4f}")
            
            if abs(total_delta) > self.delta_threshold:
                # Find and execute optimal adjustments
                adjustments = self.find_optimal_portfolio_adjustment(total_delta)
                if adjustments:
                    print("Executing the following adjustments:")
                    for contract, qty in adjustments:
                        print(f"{'BUY' if qty > 0 else 'SELL'} {abs(qty)} {contract.localSymbol}")
                    self.execute_adjustments(adjustments)
                else:
                    print("No viable adjustments found")
            
            self.ib.sleep(check_interval)

# Example usage remains similar
def main():
    ib = IB()
    try:
        ib.connect('127.0.0.1', 7497, clientId=1)
        
        restricted_strikes = {100.0, 105.0, 110.0}
        restricted_expirations = {'20240119'}
        restricted_types = {'P'}
        
        hedger = DeltaHedger(
            ib, 
            'SPY', 
            delta_threshold=0.02,
            #restricted_strikes=restricted_strikes,
            #restricted_expirations=restricted_expirations,
            #restricted_types=restricted_types
        )
        
        hedger.monitor_and_hedge()
        
    finally:
        ib.disconnect()

if __name__ == '__main__':
    main()
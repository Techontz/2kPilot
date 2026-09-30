"""Trading engine: orchestrates market data → strategy → risk → execution →
reconciliation for every account, on worker threads, under the kill switch.

Demo, paper and (eventually) live trading all use this same pipeline.
"""

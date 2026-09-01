"""
idlehive network status service

A small FastAPI app that periodically polls face over SSH for OSPF
neighbor state, ping RTT to each spoke, and which of remote spokes is the
currently active egress in routing-table=remote.
"""

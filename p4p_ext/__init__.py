# The variable concurrency is used to reduce duplicating code in the asyncio and thread versions of modules
# by using the variable for conditional importing. 
# The variable is set in p4p_ext/[asyncio,thread]/__init__.py to 'asyncio' or 'thread' respectively
# The default value is set below to 'thread'
concurrency = 'thread'
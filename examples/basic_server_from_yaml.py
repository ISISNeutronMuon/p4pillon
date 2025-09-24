# Run interactively to have the server stay up and then terminate using server.stop()
# Uncomment the lines below to turn on debugging output to the screen
import logging
import time

from p4pillon import config_reader
from p4pillon.thread.server import Server

logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(logging.StreamHandler())

filename = "examples/basic_server_recipe.yaml"
server = Server(prefix="DEV:")

config_reader.parse_config_file(filename, server)

server.start()

try:
    while True:
        # Once the server is running, you should be able to update values of the PVs
        # it is hosting through pvput calls (either directly through CLI, Phoebus or
        # the p4p Client)
        time.sleep(5)
except KeyboardInterrupt:
    pass
finally:
    server.stop()

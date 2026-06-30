from app import app
from database import init_database
from driver_service import start_driver_monitor

init_database()
start_driver_monitor()

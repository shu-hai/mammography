#!/usr/bin/python
import sys


class logger(object):
    def __init__(self, log_path):
        self.terminal = sys.stdout
        file_path = log_path + 'log.txt'
        self.log = open(file_path, "wb")
        
    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()
        
    def flush(self):
        #this flush method is needed for python 3 compatibility.
        #this handles the flush command by doing nothing.
        #you might want to specify some extra behavior here.
        pass
    
    

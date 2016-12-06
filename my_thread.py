#!/usr/bin/python
import threading
import timeit
import Queue
import gc

import os
import psutil

import dicom
import os
import numpy as np
import pandas as pd
import sys
from matplotlib import pyplot as plt
from matplotlib import cm
import scipy
from scipy import signal as signal
from scipy.optimize import minimize, rosen, rosen_der
from scipy.ndimage import filters as filters
from scipy.ndimage import measurements as measurements
from skimage.transform import (hough_line, hough_line_peaks, probabilistic_hough_line)
import pywt
from skimage import measure
from sklearn import svm
from sklearn.externals import joblib
from skimage import feature
from skimage.morphology import disk
from skimage.filters import roberts, sobel, scharr, prewitt, threshold_otsu, rank
from skimage.util import img_as_ubyte
from skimage.feature import corner_harris, corner_subpix, corner_peaks
from scipy import ndimage as ndi

#import my classes
from breast import breast
from feature_extract import feature
from read_files import spreadsheet


#for tracking memory
from pympler.tracker import SummaryTracker
from pympler.asizeof import asizeof


"""
my_thread:

Description: 
class that holds all of the data and methods to be used within each thread for 
processing and training the model. This class uses threading.Thread as the base class,
and extends on it's functionality to make it suitable for our use.

Memeber variables are included such as the feature object defined in feature_extract.py
Each thread will have a feature object as a member variable, and will use this member
to do the bulk of the processing. This class is defined purely to parellelize the workload
over multiple cores.


Some reference variables such as a queue, lock and exit flag are shared statically amongst all of 
the instances. Doing this just wraps everything a lot nicer.
"""


class my_thread(threading.Thread):    
    
    #some reference variables that will be shared by all of the individual thread objects
    #whenever any of these reference variables are accessed, the thread lock should be applied,
    #to ensure multiple threads arent accessing the same memory at the same time
    
    q = Queue.Queue(1000)        #queue that will contain the filenames of the scans
    q_cancer = Queue.Queue(1000) #queue that will contain the cancer status of the scans
    t_lock = threading.Lock()
    exit_flag = False
    error_files = []   #list that will have all of the files that we failed to process
    cancer_status = []
    
    """
    __init__()
    
    Description:
    Will initialise the thread and the feature member variable.
    
    @param thread_id = integer to identify individual thread s
    @param num_images_total = the number of images about to be processed in TOTAL
    @param data_path = the path to the scans, will vary depending on which machine we are on
    
    """
    
    def __init__(self, thread_id, no_images_total, data_path = './pilot_images/'):
        threading.Thread.__init__(self)
        self.t_id = thread_id
        self.scan_data = feature(levels = 3, wavelet_type = 'haar', no_images = no_images_total ) #the object that will contain all of the data
        self.scan_data.current_image_no = 0    #initialise to the zeroth mammogram
        self.data_path = data_path
        self.time_process = []   #a list containing the time required to perform preprocessing
                                 #on each scan, will use this to find average of all times
        self.scans_processed = 0
        
    """
    run()
    
    Description:
    Overloaded version of the Thread modules run function, which is called whenever the thread
    is started. This will essentially just call the processing member function , which handles
    the sequence for the running of the thread
    
    """
    
    def run(self):
        #just run the process function
        self.process()
        
        
        
    """
    process()
    
    Description:
    The bulk of the running of the thread is handeled in this function. This function handles
    the sequence of processing required, ie. loaading scans, preprocessing etc.
    
    Also handles synchronization of the threads, by locking the threads when accessing the 
    class reference variables, such as the queues
    
    The process function will continue to loop until the queues are empty. When the queues
    are empty, the reference variable (exit_flag) will be set to True to tell us that the processing
    is about ready to finish.
    
    If there is an error with any file, the function will add the name of the file where the error
    occurred so it can be looked at later on, to see what exactly caused the error. 
    This will raise a generic exception, and will just mean we skip to the next file if we 
    encounter an error.
    
    Will also time each of the preprocessing steps to see how long the preprocessing of each
    scan actually takes, just to give us an idea
    
    Finally, will make sure we will look at parts of the feature array that are actually valid
    """
    
    def process(self):
        
        #while there is still names on the list, continue to loop through
        #while the queue is not empty        
        while not self.exit_flag:
            #lock the threads so only one is accessing the queue at a time
            #start the preprocessing timer
            start_time = timeit.default_timer()
            self.t_lock.acquire()
            if(not (self.q.empty()) ):
                file_path = self.data_path + self.q.get()
                self.cancer_status.append( self.q_cancer.get() )
                self.t_lock.release()
                
                try:
                #now we have the right filename, lets do the processing of it
                    self.scan_data.initialise(file_path)
                    self.scan_data.preprocessing()
                    self.scan_data.get_features()

                    #testing the feature extraction to see how if it is being stored correctly
                    print('Testing Features')
                    level = 1
                    image_no = self.scan_data.current_image_no
                    print('image_no = %d' %image_no)
                    #print(self.scan_data.homogeneity)
                    #print(self.scan_data.homogeneity[image_no][0])
                    #print(self.scan_data.homogeneity[image_no][level])
                    #print(self.scan_data.homogeneity[image_no][2])
                    #print(self.scan_data.energy[image_no][level])
                    #print(self.scan_data.energy[image_no][level][2])
                    #print(self.scan_data.contrast[image_no][level])
                    #print(self.scan_data.dissimilarity[image_no][level])
                    #print(self.scan_data.correlation[image_no][level])
                    #print(self.scan_data.entropy[image_no][level])


                    #now that we have the features, we want to append them to the list of features
                    #The list of features is shared amongst all of the class instances, so
                    #before we add anything to there, we should lock other threads from adding
                    #to it
                    self.t_lock.acquire()
                    self.cancer_status.append(self.q_cancer.get())
                    self.t_lock.release()
                    self.time_process.append(timeit.default_timer() - start_time)
                    print('time = %d s' %self.time_process[-1])
                    self.scan_data.current_image_no += 1   #increment the image index
                    self.scans_processed += 1              #increment the image counter
                    
                    #just doing a few scans at the moment whilest debugging
                    if(self.scans_processed > 10):
                        with self.q.mutex: self.q.queue.clear()
                    
                except:
                    print('Error with current file %s' %(file_path))
                    self.error_files.append(file_path)
                    
                self.scan_data.cleanup()
                gc.collect()
            else:
                self.t_lock.release()
                
                
                
                
        #there is nothing left on the queue, so we are ready to exit
        #before we exit though, we just need to crop the feature arrays to include
        #only the number of images we looked at in this individual thread
        self.scan_data._crop_features(self.scans_processed)
        print('Thread %d is out' %self.t_id)

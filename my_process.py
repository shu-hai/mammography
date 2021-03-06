#!/usr/bin/python
import threading
import timeit
import time
import gc
from multiprocessing import Process, Lock, Queue
from multiprocessing.managers import BaseManager

import os
#import psutil


import dicom
import os
import numpy as np
import pandas as pd
import sys
from matplotlib import pyplot as plt
from matplotlib import cm
import networkx as nx
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
from itertools import chain

#import my classes
from mammogram.breast import breast
from mammogram.feature_extract import feature
from db import spreadsheet

#for tracking memory
#from pympler.tracker import SummaryTracker
#from pympler.asizeof import asizeof





class shared(object):
    """
    shared()
    
    Description:
    some reference variables that will be shared by all of the individual process objects
    whenever any of these reference variables are accessed, the process lock should be applied,
    to ensure multiple processs arent accessing the same memory at the same time
    """
    
    q = Queue(750000)             #queue that will contain the filenames of the scans
    q_cancer = Queue(750000)      #queue that will contain the cancer status of the scans
    q_laterality = Queue(750000)  #queue that will contain the laterality (view) of the scans
    q_exam = Queue(750000)        #queue that will contain the exam index of the scans
    q_subject_id = Queue(750000)  #queue that will contain the subject ID of the scans
    q_bc_history = Queue(750000)
    q_bc_first_degree_history = Queue(750000)
    q_bc_first_degree_history_50 = Queue(750000)
    q_anti_estrogen = Queue(750000)
    q_bbs = Queue(750000)
    q_conf = Queue(750000)
    
    t_lock = Lock()
    exit_flag = False
    error_files = []   #list that will have all of the files that we failed to process
    scan_no = 0
    cancer_count = 0
    benign_count = 0
    feature_array = []
    class_array = []
    laterality_array = []
    exam_array = []
    subject_id_array = []
    bc_history_array = []
    bc_first_degree_array = []
    bc_first_degree_50_array = []
    anti_estrogen_array = []
    skipped_ids = []
    skipped_lateralities = []
    skipped_cancer_status = []
    skipped_exam = []
    save_timer = time.time()
    save_time = 3600      #save once an hour or every 3600 seconds

    
    ##########################################
    #
    #List of helper functions that are used to
    #access the data in the manager
    #
    ##########################################
    
    def q_get(self):
        return self.q.get()
    
    def q_cancer_get(self):
        return self.q_cancer.get()
    
    def q_laterality_get(self):
        return self.q_laterality.get()
    
    def q_exam_get(self):
        return self.q_exam.get()
    
    def q_subject_id_get(self):
        return self.q_subject_id.get()    
    
    def q_bc_history_get(self):
        return self.q_bc_history.get()
        
    def q_bc_first_degree_history_get(self):
        return self.q_bc_first_degree_history.get()
        
    def q_bc_first_degree_history_50_get(self):
        return self.q_bc_first_degree_history_50.get()
        
    def q_anti_estrogen_get(self):
        return self.q_anti_estrogen.get()
    
    def q_bbs_get(self):
        return self.q_bbs.get()
    
    def q_conf_get(self):
        return self.q_conf.get()
    
    def q_put(self, arg):
        self.q.put(arg)
        
    def q_cancer_put(self, arg):
        self.q_cancer.put(arg)
        
    def q_laterality_put(self, arg):
        self.q_laterality.put(arg)
        
    def q_exam_put(self, arg):
        self.q_exam.put(arg)
        
    def q_subject_id_put(self, arg):
        return self.q_subject_id.put(arg)    
    
    def q_bc_history_put(self, arg):
        self.q_bc_history.put(arg)
        
    def q_bc_first_degree_history_put(self, arg):
        self.q_bc_first_degree_history.put(arg)
        
    def q_bc_first_degree_history_50_put(self, arg):
        self.q_bc_first_degree_history_50.put(arg)
        
    def q_anti_estrogen_put(self, arg):
        self.q_anti_estrogen.put(arg)
        
    def q_bbs_put(self, arg):
        self.q_bbs.put(arg)
        
    def q_conf_put(self, arg):
        self.q_conf.put(arg)
        
    def q_empty(self):
        return self.q.empty()
    
    def q_size(self):
        return self.q.qsize()
    
    def t_lock_acquire(self):
        self.t_lock.acquire()
        
    def t_lock_release(self):
        self.t_lock.release()
        
    def set_scan_no(self, scan_no):
        self.scan_no = scan_no
        
    def get_scan_no(self, scan_no):
        return self.scan_no
    
    def error_files_put(self, erf):
        self.error_files.append(erf)
        
    def get_exit_status(self):
        return self.exit_flag
    
    def set_exit_status(self, status):
        self.exit_flag = status
        
    def inc_cancer_count(self):
        self.cancer_count += 1
        
    def inc_benign_count(self):
        self.benign_count += 1
        
    def get_cancer_count(self):
        return self.cancer_count
    
    def get_benign_count(self):
        return self.benign_count
    
    def inc_scan_count(self):
        self.scan_no += 1
        
    def get_scan_count(self):
        return self.cancer_count
    
    def get_error_files(self):
        return self.error_files
    
    def add_error_file(self, f):
        self.error_files.append(f)
        
    def first_features_added(self):
        return (len(self.feature_array) == 0)
       
    def set_feature_array(self, feature_array):
        self.feature_array = feature_array
        
    def set_class_array(self, class_array):
        self.class_array = class_array
        
    def append_feature_array(self, feature_array):
        self.feature_array.append(feature_array)
        
    def append_class_array(self, class_array):
        self.class_array.append(class_array)
        
    def get_feature_array(self):
        return self.feature_array
        
    def get_class_array(self):
        return self.class_array
    
    def get_laterality_array(self):
        return self.laterality_array
    
    def get_exam_array(self):
        return self.exam_array
    
    def get_subject_id_array(self):
        return self.subject_id_array
    
    def get_bc_history_array(self):
        return self.bc_history_array
    
    def get_bc_first_degree_history_array(self):
        return self.bc_first_degree_history_array
    
    def get_bc_first_degree_history_50_array(self):
        return self.bc_first_degree_history_50_array
    
    def get_anti_estrogen_array(self):
        return self.anti_estrogen_array
    
    def get_skipped_ids(self):
        return self.skipped_ids
    
    def get_skipped_lateralities(self):
        return self.skipped_lateralities   
    
    def get_skipped_cancer_status(self):
        return self.skipped_cancer_status   
    
    def get_skipped_exam(self):
        return self.skipped_exam
    
        
    ###################################
    #
    # Functions to handle timing of saving data
    #
    ###################################
    
    def init_timer(self):
        """
        init_timer()

        Description:
        Initialise timer
        """
        self.save_timer = time.time()
        
    
    
    def reset_timer(self):
        """
        reset_timer()

        Description: 
        Will just reinitialise both timers
        This function is just here as a convenience
        """
        self.init_timer()
        
        
    def save_time_elapsed(self):
        return ( (time.time() - self.save_timer) >= self.save_time)
    
    
    def periodic_save_features(self, save_path):
        self.t_lock_acquire()
        X = np.array(self.get_feature_array())
        Y = np.array(self.get_class_array())
        lateralities = np.array(self.get_lateralities_array(), dtype='S1')
        exams = np.array(self.get_exams(), dtype=np.int)
        subject_ids = np.array(self.get_subject_ids(), dtype='S12')
        
        np.save(os.path.join(save_path, 'model_data/X_temp'), X)
        np.save(os.path.join(save_path, 'model_data/Y_temp'), Y)
        np.save(os.path.join(command_line_args.save_path,'model_data/lateralities_temp'), lateralities)
        np.save(os.path.join(command_line_args.save_path, 'model_data/exams_temp'), exams)
        np.save(os.path.join(command_line_args.save_path, 'model_data/subject_ids_temp'), subject_ids)
        
        print('Saved Temporary Data')
        print(X.shape)
        #reset the timer
        self.reset_timer()
        self.t_lock_release()



    
    def add_features(self,X, Y, laterality, exam, subject_id, bc_histories, bc_first_degree_histories, bc_first_degree_histories_50, anti_estrogens):
        """    
        add_features()

        Description: 
        This function will add all of the features from scans processed
        in a single process/process and add them to the list in the manager

        @params
        X = N x M array containing the features from the scans processed in the process
            N = number of scans processed
            M = Number of features per scan

        Y = 1D array containing status of each of training scans
        laterality = list containing the laterality of each scan (either 'L' or 'R')
        exam = list containing the examination number of each scan
        subject_id = list containing the subject ID of all the scans

        """

        #request lock for this process
        self.t_lock_acquire()
        #if this is the first set of features to be added, we should just initially
        #set the features in the manager to equal X and Y.
        #Otherwise, use extend on the list. Just a nicer way of doing it so we
        #don't have to keep track of indicies and sizes
        if(self.first_features_added()):
            self.feature_array = X
            self.class_array = Y
            self.laterality_array = laterality
            self.exam_array = exam
            self.subject_id_array = subject_id
            self.bc_history_array = bc_histories
            self.bc_first_degree_history_array = bc_first_degree_histories
            self.bc_first_degree_history_50_array = bc_first_degree_histories_50
            self.anti_estrogen_array = anti_estrogens
            
        else:
            print(np.shape(self.feature_array))
            self.feature_array.extend(X)
            self.class_array.extend(Y)
            self.laterality_array.extend(laterality)
            self.exam_array.extend(exam)
            self.subject_id_array.extend(subject_id)
            self.bc_history_array.extend(bc_histories)
            self.bc_first_degree_history_array.extend(bc_first_degree_histories)
            self.bc_first_degree_history_50_array.extend(bc_first_degree_histories_50)
            self.anti_estrogen_array.extend(anti_estrogens)
            
        #we are done so release the lock
        self.t_lock_release()
        
        
        
    #these are files we either had an error with, or we are using
    #regions found from the RCNN and none of them were good
    def add_skipped_files(self, skipped_ids, skipped_lateralities, skipped_cancer_status, skipped_exam):
        self.t_lock_acquire()
        if(len(self.skipped_ids) < 0):
            self.skipped_ids = skipped_ids
            self.skipped_cancer_status = skipped_cancer_status
            self.skipped_lateralities = skipped_lateralities
            self.skipped_exam = skipped_exam
        elif(len(skipped_ids) > 0):
            self.skipped_ids.extend(skipped_ids)
            self.skipped_lateralities.extend(skipped_lateralities)
            self.skipped_cancer_status.extend(skipped_cancer_status)
            self.skipped_exam.append(skipped_exam)
            print(skipped_exam)
        self.t_lock_release()
        
                
class my_manager(BaseManager):
    pass

#Defining the manager that is used for the main program and that it is a shared
#manager
my_manager.register('shared', shared)





class my_process(Process):    
    """
    my_process:

    Description: 
    class that holds all of the data and methods to be used within each process for 
    processing and training the model. This class uses processing.Process as the base class,
    and extends on it's functionality to make it suitable for our use.

    Memeber variables are included such as the feature object defined in feature_extract.py
    Each process will have a feature object as a member variable, and will use this member
    to do the bulk of the processing. This class is defined purely to parellelize the workload
    over multiple cores.


    Some reference variables such as a queue, lock and exit flag are shared statically 
    amongst all of the instances. Doing this just wraps everything a lot nicer.
    """

    
    
    def __init__(self, process_id, no_images_total, manager, command_line_args):
        """
        __init__()

        Description:
        Will initialise the process and the feature member variable.

        @param process_id = integer to identify individual process s
        @param num_images_total = the number of images about to be processed in TOTAL
        @param command_line_args = arguments object that holds the arguments parsed from 
               the command line. These areguments decide whether we are training,
                preprocessing etc.

        """
        Process.__init__(self)
        print('Initialising process %d' %process_id)
        self.manager = manager
        self.t_id = process_id
        self.scan_data = feature(levels = 2, wavelet_type = 'db4', no_images = no_images_total ) #the object that will contain all of the data
        self.scan_data.current_image_no = 0    #initialise to the zeroth mammogram
        self.data_path = command_line_args.input_path
        self.time_process = []   #a list containing the time required to perform preprocessing
                                 #on each scan, will use this to find average of all times
        self.scans_processed = 0
        self.cancer_status = []        
        self.subject_ids = []
        self.lateralities = []
        self.bc_histories = []
        self.bc_first_degree_histories = []
        self.bc_first_degree_histories_50 = []
        self.anti_estrogens = []
        self.exam_nos = []
        self.training = command_line_args.training
        self.preprocessing = command_line_args.preprocessing
        self.validation = command_line_args.validation
        self.save_path = command_line_args.save_path
        self.challenge_submission = command_line_args.challenge_submission
        
        self.skipped_ids = []
        self.skipped_lateralities = []
        self.skipped_cancer_status = []
        self.skipped_exam = []
        
        #some variables that are used to time the system for adding files to the shared manager
        self.add_timer = time.time()
        #add features every 13 minutes
        #made it not a factor of 60 minutes
        self.add_time = 780
        
                
    
    def run(self):
        """
        run()

        Description:
        Overloaded version of the Process modules run function, which is called whenever 
        the process is started. This will essentially just call the processing member function,
        which handles the sequence for the running of the process
        """
        #just run the process function
        print('Begin process in process %d' %self.t_id)
        self._process()
        
            
    
    def _process(self):
        """
        _process()

        Description:
        The bulk of the running of the process is handeled in this function. This function handles
        the sequence of processing required, ie. loaading scans, preprocessing etc.

        Also handles synchronization of the processs, by locking the processs when accessing the 
        class reference variables, such as the queues

        The process function will continue to loop until the queues are empty. When the queues
        are empty, the reference variable (exit_flag) will be set to True to tell us that the 
        processing is about ready to finish.

        If there is an error with any file, the function will add the name of the file where the 
        error occurred so it can be looked at later on, to see what exactly caused the error. 
        This will raise a generic exception, and will just mean we skip to the next file if we 
        encounter an error.

        Will also time each of the preprocessing steps to see how long the preprocessing of each
        scan actually takes, just to give us an idea

        Finally, will make sure we will look at parts of the feature array that are actually valid
        """

        print('Running process %d' %self.t_id)
        #while there is still names on the list, continue to loop through
        #while the queue is not empty
        while( not self.manager.get_exit_status()):
            #variable that is used to see if we want to process this scan
            #or skip it
            valid = True
            #lock the processs so only one is accessing the queue at a time
            #start the preprocessing timer
            start_time = timeit.default_timer()
            self.manager.t_lock_acquire()
            if(not (self.manager.q_empty()) ):
                
                file_path = os.path.join(self.data_path, self.manager.q_get())
                #get the cancer status.
                #if we are validating on the synapse servers, the cancer status is not
                #given, so I have set them all to false in read_files
                self.cancer_status.append(self.manager.q_cancer_get())
                #add the rest of the metadata to the list
                self.subject_ids.append(self.manager.q_subject_id_get())
                self.lateralities.append(self.manager.q_laterality_get())
                self.exam_nos.append(self.manager.q_exam_get())
                self.bc_histories.append(self.manager.q_bc_history_get())
                self.bc_first_degree_histories.append(self.manager.q_bc_first_degree_history_get())
                self.bc_first_degree_histories_50.append(self.manager.q_bc_first_degree_history_50_get())
                self.anti_estrogens.append(self.manager.q_anti_estrogen_get())
                bbs = (self.manager.q_bbs_get())
                conf = (self.manager.q_conf_get())                
                #if this scan is cancerous
                if(self.cancer_status[-1]):
                    self.manager.inc_cancer_count()
                    print('cancer count = %d' %self.manager.get_cancer_count())
                    
                #otherwise it must be a benign scan
                else:
                    self.manager.inc_benign_count()
                    print('benign count = %d' %self.manager.get_benign_count())
                    
                    
                #if we have enough benign scans, lets not worry about it this scan
                #as we have enough for training purposes
                #if we are validating, the benign count will most likely be more,
                #but we want to keep going to try and classify benign scans
                #if it is a cancerous file though we should keep going
                if(self.manager.get_benign_count() > 60000) & (not self.validation) & (not self.cancer_status[-1]):
                    self._remove_most_recent_metadata_entries()
                    print('Skipping %s since we have enough benign scans :)' %(file_path))
                    #now we can just continue with this loop and go on about our business
                    #this will go to next iteration of the while loop
                    valid = False
                    
                    
                #if the queue is now empty, we should wrap up and
                #get ready to exit
                if(self.manager.q_empty()):
                    print('Queue is Empty')
                    self.manager.set_exit_status(True)                
                    
                    
                #this is just here whilst debugging to shorten the script
                #################
                #if(self.manager.get_benign_count() > 50):
                #    print('benign Count is greater than 20 so lets exit')
                #    self.manager.set_exit_status(True)                
                
                #are done getting metadata and filenames from the queue, so unlock processes
                self.manager.t_lock_release()
                print('Queue size = %d' %self.manager.q_size())
                
                #if we have made it here, and it isn't a scan we wish to skip
                #we should get busy processing some datas :)
                if(valid):
                    try:
                        #now we have the right filename, lets do the processing of it
                    #if we are doing the preprocessing, we will need to read the file in correctly
                        self.scan_data.initialise(file_path, self.preprocessing)
                        
                        #begin preprocessing steps
                        if(self.preprocessing):
                            self.scan_data.preprocessing()
                            if(not self.challenge_submission):# & (not self.validation):
                                self._save_preprocessed()
                                
                        #if confidence is equal to zero, we are using the regions
                        #found with the rcnn, we just didnt find any for this image   
                        if(conf[0][0] != -1):
                            valid = self.scan_data.get_features(bbs, conf)
                            
                        if(conf[0][0] == -1) | (not valid):
                            print('no good region for this image')
                            self.skipped_ids.append(self.subject_ids[-1])
                            self.skipped_lateralities.append(self.lateralities[-1])
                            self.skipped_cancer_status.append(self.cancer_status[-1])
                            self.skipped_exam.append(self.exam_nos[-1])
                            self._remove_most_recent_metadata_entries()
                            continue
                           
                        #now that we have the features, we want to append them to
                        #the list of features
                        #The list of features is shared amongst all of the class instances, so
                        #before we add anything to there, we should lock other processs from adding
                        #to it
                        self.scan_data.current_image_no += 1   #increment the image index
                        lock_time = timeit.default_timer()
                        #now increment the total scan count as well
                        self._inc_total_scan_count()
                        
                        
                    except Exception as e:
                        #raise #if debugging
                        #print the error message
                        print e 
                        print('Error with current file %s' %(file_path))
                        self.manager.add_error_file(file_path)
                        #get rid of the last cancer_status flag we saved, as it is no longer
                        #valid since we didn't save the features from the scan
                        #
                        #NOTE: we won't want to get rid of these features whilst validating
                        #on the synapse server. Just find features from what we have and run with it
                        if(True):
                            #(not self.validation) & ((not self.challenge_submission) | self.preprocessing):
                            print('removing this scan')
                            self._remove_most_recent_metadata_entries()
                        #if we are validating for the challenge, lets try our best on what we have
                        
                        else:
                            self.scan_data.data = np.copy(self.scan_data.original_scan)
                            #should be safe to have this outside a try and catch, as it
                            #should never fail
                            self.scan_data.get_features()
                            self.scan_data.current_image_no += 1   #increment the image index
                            self._inc_total_scan_count()
                            
                sys.stdout.flush()
                self.scan_data.cleanup()
                gc.collect()
                
            else:
                #we should just release the lock on the processes
                self.manager.t_lock_release()                    
                
                
        #there is nothing left on the queue, so we are ready to exit
        #before we exit though, we just need to crop the feature arrays to include
        #only the number of images we looked at in this individual process
        self._add_features()
        
        #now just print a message to say that we are done
        print('Process %d is out' %self.t_id)
        sys.stdout.flush()
        
                
    def _remove_most_recent_metadata_entries(self):
        """
        _remove_most_recent_metadata_entries():
        
        Description:
        Function will remove the data entries from the last scan if there was
        and error, or if there was too many scans collected etc.
        """
        
        del self.cancer_status[-1]
        del self.lateralities[-1]
        del self.exam_nos[-1]
        del self.subject_ids[-1]        
        del self.bc_histories[-1]
        del self.bc_first_degree_histories[-1]
        del self.bc_first_degree_histories_50[-1]
        del self.anti_estrogens[-1]
        
        
        
    def _add_time_elapsed(self):
        return (time.time() - self.add_timer) > self.add_time
    
    
    
    def _flatten(self, x):
        """
        _flatten()

        Description:
        Flatten one level of nesting
        """
        return chain.from_iterable(x)
    
    
    
    
    def _save_preprocessed(self):
        """
        _save_preprocessed()
        
        Description:
        After a file has been preprocessed, will write it to file so we don't have to do 
        it again. 
        Before saving to file, we will convert all of the Nans to -1. This allows us to save 
        the data as a 16-bit integer instead of 32-64 bit float.
        
        Using half the amount of disk space == Awesomeness
        Will just have to convert it when loading before performing feature extraction
        """
        
        file_path = self.save_path +  self.scan_data.file_path[-10:-4]
        boundary_path = os.path.join(self.save_path, 'boundaries',  self.scan_data.file_path[-10:-4])
        boundary = np.zeros((2,len(self.scan_data.boundary))).astype(np.int16)
        boundary[0,:] = np.array(self.scan_data.boundary)
        boundary[1,:] = np.array(self.scan_data.boundary_y)
        print(file_path)
        #copy the scan data
        temp = np.copy(self.scan_data.data)
        #set all Nan's to -1
        temp[np.isnan(temp)] = -1
        temp = temp.astype(np.int16)
        #now save the data
        np.save(file_path, temp)
        np.save(boundary_path, boundary)        
        
        
        
    def _inc_total_scan_count(self):
        """
        _inc_scan_count()
        
        Description:
        Will just increment the scans processed
        
        """
        self.manager.t_lock_acquire()
        self.manager.inc_scan_count()
        self.manager.t_lock_release()                    
        
        
            
    def _add_features(self):
        """
        add_features()
        
        Description:
        Am done with selection and aquisition of features. 
        Will add the features from this process to the manager
        
        """
        
        self.scan_data._crop_features(self.scan_data.current_image_no)
        
        X = []
        Y = []
        for t_ii in range(0, self.scan_data.current_image_no):
            X.append([])
            for lvl in range(self.scan_data.levels):                
                homogeneity = self.scan_data.homogeneity[t_ii][lvl]
                entropy = self.scan_data.entropy[t_ii][lvl]
                energy = self.scan_data.energy[t_ii][lvl]
                contrast = self.scan_data.contrast[t_ii][lvl]
                dissimilarity = self.scan_data.dissimilarity[t_ii][lvl]
                correlation = self.scan_data.correlation[t_ii][lvl]
                
                #wave_energy = self.scan_data.wave_energy[t_ii][lvl]
                #wave_entropy = self.scan_data.wave_entropy[t_ii][lvl]
                #wave_kurtosis = self.scan_data.wave_kurtosis[t_ii][lvl]
                
                X[t_ii].extend(self._flatten(homogeneity))
                X[t_ii].extend(self._flatten(entropy))
                X[t_ii].extend(self._flatten(energy))
                X[t_ii].extend(self._flatten(contrast))
                X[t_ii].extend(self._flatten(dissimilarity))
                X[t_ii].extend(self._flatten(correlation))
                
            #add the density measure for this scan
            X[t_ii].append(self.scan_data.density[t_ii])
            #set the cancer statues for this scan            
            Y.append(self.cancer_status[t_ii])    
        self.manager.add_skipped_files(self.skipped_ids, self.skipped_lateralities, self.skipped_cancer_status, self.skipped_exam)
        #now add the features from this list to to conplete list in the manager
        self.manager.add_features(X, Y, self.lateralities, self.exam_nos, self.subject_ids, self.bc_histories, self.bc_first_degree_histories, self.bc_first_degree_histories_50, self.anti_estrogens)
        #reinitialise the feature list in the scan_data member
        self.scan_data.reinitialise_feature_lists()
        #reinitialise the metadata
        self.cancer_status = []        
        self.subject_ids = []
        self.lateralities = []
        self.exam_nos = []
        
        #set the number of scans processed back to zero
        self.scan_data.current_image_no = 0                
        #reset the timer
        self.add_timer = time.time()

#!/usr/bin/python

import dicom
import os
import numpy as np
import pandas as pd
import sys
import getopt

#this allows us to create figures when no display environment variable is available
import matplotlib as mpl
mpl.use('Agg')
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
from sklearn.datasets import dump_svmlight_file, load_svmlight_file
from sklearn.metrics import roc_auc_score
from sklearn.decomposition import PCA
from skimage import feature
from skimage.morphology import disk
from skimage.filters import roberts, sobel, scharr, prewitt, threshold_otsu, rank
from skimage.util import img_as_ubyte
from skimage.feature import corner_harris, corner_subpix, corner_peaks
from scipy import ndimage as ndi
import subprocess
import pickle

from itertools import chain
import timeit
from multiprocessing import Process, Lock, Queue, cpu_count
from my_process import my_process, shared, my_manager
from multiprocessing.managers import BaseManager

#import my modules
from metric import *
from kl_divergence import *
#import my classes
from mammogram.breast import breast
from mammogram.feature_extract import feature
from db import spreadsheet
from log import logger
from cmd_arguments import arguments


##################################
#
# Helper functions for the main parts of the program
# called from this script
#
##################################

def flatten(x):
    "Flatten one level of nesting"
    return chain.from_iterable(x)



def create_classifier_arrays(shared):
    
    #convert the list of features and class discriptors into arrays
    print shared.get_laterality_array()
    X = np.array(shared.get_feature_array())
    Y = np.array(shared.get_class_array())
    lateralities = np.array(shared.get_laterality_array())
    exams = np.array(shared.get_exam_array(), dtype=np.int)
    subject_ids = np.array(shared.get_subject_id_array())
    bc_histories = np.array(shared.get_bc_history_array(), dtype=np.int16)
    bc_first_degree_histories = np.array(shared.get_bc_first_degree_history_array(), dtype=np.int16)
    bc_first_degree_histories_50 = np.array(shared.get_bc_first_degree_history_50_array(), dtype=np.int16)
    anti_estrogens = np.array(shared.get_anti_estrogen_array(), dtype=np.int16)
    
    return X, Y, lateralities, exams, subject_ids, bc_histories, bc_first_degree_histories, bc_first_degree_histories_50, anti_estrogens



def my_pickle_save(data, filename):
    with open(filename, 'wb') as f:
        pickle.dump(data,f)
    f.close()
    
    
    
def my_pickle_load(filename):
    with open(filename, 'rb') as f:
        data = pickle.load(f)
    f.close()
    return data
    
    


def load_results(command_line_args):
    with open(os.path.join(command_line_args.save_path, 'model_data/results.txt')) as f:
        lines = f.read().splitlines()
        
    #now map the results to an array of ints
    results = np.array( map(float, lines) )
    print results
    return results


def terminal_cmd(command):
    print(command)
    os.system(command)
    
    
    
def add_metadata_features(X,Y,command_line_args):
    """
    add_metadata_features()
    
    Description:
    If we are running model for sub challenge 2, we should add the metadata features
    
    @param X = original textural based features
    @param Y = array with class identiers
    @param command_line_args = arguments object with all of our arguments we parsed in
    
    """
    
    #load in metadata
    bc_histories = np.load(os.path.join(command_line_args.save_path, 'model_data/bc_histories.npy'))
    bc_first_degree_histories = np.load(os.path.join(command_line_args.save_path, 'model_data/bc_first_degree_histories.npy'))
    bc_first_degree_histories_50 = np.load(os.path.join(command_line_args.save_path, 'model_data/bc_first_degree_histories_50.npy'))
    anti_estrogens = np.load(os.path.join(command_line_args.save_path, 'model_data/anti_estrogens.npy'))
    
    X = np.append(X,bc_histories.reshape([bc_histories.size, 1]), axis=1)
    X = np.append(X,bc_first_degree_histories.reshape([bc_first_degree_histories.size, 1]), axis=1)
    X = np.append(X,bc_first_degree_histories_50.reshape([bc_first_degree_histories_50.size, 1]), axis=1)
    X = np.append(X,anti_estrogens.reshape([anti_estrogens.size, 1]), axis=1)
    
    return X,Y
    
    

def setup_queue(shared, descriptor):
    """
    setup_queue()

    Description:
    Information from all the scans are input to this function, and is added to 
    the queue that is shared amoungst all individual processes

    @param shared = my_manager object (defined in my_process) that holds the queue for 
                    each process to access
    @param descriptor = the database (db) object that has the information on each scan that was
                         read from the spreadsheet
    """
    print("Number of Scans = %d" %(descriptor.no_scans))
    #setting up the queue for all of the processes, which contains the filenames
    #also add everything for the metadata queues
    print("Setting up Queues")
    for ii in range(0, descriptor.no_scans):
        
        shared.q_put(descriptor.filenames[ii])
        shared.q_cancer_put(descriptor.cancer_list[ii])
        shared.q_laterality_put(descriptor.laterality_list[ii])
        shared.q_exam_put(descriptor.exam_list[ii])
        shared.q_subject_id_put(descriptor.subject_id_list[ii])
        shared.q_bc_history_put(descriptor.bc_history_list[ii])
        shared.q_bc_first_degree_history_put(descriptor.bc_first_degree_history_list[ii])
        shared.q_bc_first_degree_history_50_put(descriptor.bc_first_degree_history_50_list[ii])
        shared.q_anti_estrogen_put(descriptor.anti_estrogen_list[ii])
        shared.q_bbs_put(descriptor.bbs_list[ii])
        shared.q_conf_put(descriptor.conf_list[ii])
    print('Set up Queues')
    
    

##################################
#
# Programs that are specified to run via command line arguments
#
##################################


def begin_processes(command_line_args, descriptor):
    """
    begin_processes()

    Description:

    Is the main method in this program.
    This will initiate the specified number of processes to handle the mammograms.
    Command line arguments are supplied to indicate whether the individual processes
    should be preprocessing the raw mammography data, extracting features or performing both
    tasks.

    @param command_line_args = arguments object that will have all of the relevant information
                               parsed from the command line
    @param descriptor = the database (db) object that has the information on the scans
    """
    #initialise list of processes
    processes = []
    id = 0
    num_processes = cpu_count() - 3
    print("Number of processes to be initiated = %d" %num_processes )
    #initialise manager that will handle sharing of information between the processes
    man = my_manager()
    man.start()
    shared = man.shared()
    setup_queue(shared, descriptor)
    #Create new processes
    print('Creating processes')
    for ii in range(0,num_processes):
        sys.stdout.flush()
        process = my_process(id, descriptor.no_scans, shared, command_line_args)
        process.start()
        processes.append(process)
        id += 1    
    print('Started Processes')
    
    #now some code to make sure it all runs until its done
    #keep this main process open until all is done
    while (not shared.get_exit_status()):
        #just so we flush all print statements to stdout
        sys.stdout.flush()
        pass
    
    #queue is empty so we are just about ready to finish up
    #set the exit flag to true
    #wait until all processes are done
    for t in processes:
        t.join()
        
        
    #all of the processes are done, so we can now we can use the features found to train
    #the classifier    
    #will be here after have run through everything
    #lets save the features we found, and the file ID's of any that
    #created any errors so I can have a look later
    #will just convert the list of error files to a pandas database to look at later
    error_database = pd.DataFrame(shared.get_error_files())
    #will save the erroneous files as csv
    error_database.to_csv('error_files.csv')
    
    X, Y, lateralities,
    exams, subject_ids, bc_histories,
    bc_first_degree_histories, bc_first_degree_histories_50,
    anti_estrogens = create_classifier_arrays(shared)
 
    #if we specified we want to do PCA
    if(command_line_args.principal_components):
        print('Performing PCA on texture features with %d principal components' %(command_line_args.principal_components))
        pca = PCA(n_components=command_line_args.principal_components)
        X = pca.fit_transform(X)
        
    if(command_line_args.kl_divergence):
        #if we are training, lets find the indicies with that we are using
        if(not command_line_args.validation):
            kld = kl_divergence(X[Y,:], X[Y==False,:], command_line_args.kl_divergence)
            X = X[:,kld]
            #save the kld features
            np.save(os.path.join(command_line_args.model_path, 'kld'), kld)
        #if we are validating, select the same feature indecies we used whilst training
        else:
            kld = np.load(os.path.join(command_line_args.model_path, 'kld.npy'))
            X = X[:,kld]
            
    #save this data in numpy format, and in the LIBSVM format
    print X.shape
    print('Saving the final data')
    np.save(os.path.join(command_line_args.save_path , 'model_data/X'), X)
    np.save(os.path.join(command_line_args.save_path , 'model_data/Y'), Y)
    np.save(os.path.join(command_line_args.save_path , 'model_data/lateralities'), lateralities)
    np.save(os.path.join(command_line_args.save_path , 'model_data/exams'), exams)
    np.save(os.path.join(command_line_args.save_path , 'model_data/subject_ids'), subject_ids)
    np.save(os.path.join(command_line_args.save_path , 'model_data/bc_histories'), bc_histories)
    np.save(os.path.join(command_line_args.save_path , 'model_data/bc_first_degree_histories'), bc_first_degree_histories)
    np.save(os.path.join(command_line_args.save_path , 'model_data/bc_first_degree_histories_50'), bc_first_degree_histories_50)
    np.save(os.path.join(command_line_args.save_path , 'model_data/anti_estrogens'), anti_estrogens)        
    #save the files that we skipped
    my_pickle_save(shared.get_skipped_ids(),
                   os.path.join(command_line_args.save_path,
                                'model_data/skipped_ids'))
    my_pickle_save(shared.get_skipped_lateralities(),
                   os.path.join(command_line_args.save_path,
                                'model_data/skipped_lateralities'))
    my_pickle_save(shared.get_skipped_cancer_status(),
                   os.path.join(command_line_args.save_path,
                                'model_data/skipped_cancer_status'))
    my_pickle_save(shared.get_skipped_exam(),
                   os.path.join(command_line_args.save_path,
                                'model_data/skipped_exam'))
    
    

def preprocessing(command_line_args, descriptor):
    """
    preprocessing()
    
    Description:
    
    Will call the function to begin all processes and start preprocessing all of the data
    """    
    #basically can just run all the processes
    begin_processes(command_line_args, descriptor)
    
    

def train_model(command_line_args, descriptor):
    """
    train_model()
    
    Description:
    If the command line arguments specified that we should train the model,
    this function will be called. Uses the GPU enhanced version of LIBSVM to train the model.
    
    In the command_line_args object, a path to a file containing the variables to train the models is found.
    
    """
    
    #if we are forcing to capture the features, we will do so now.
    #otherwise we will use the ones found during initial preprocessing
    #force this with the -f argument 
    print command_line_args.extract_features
    if(command_line_args.extract_features):
        begin_processes(command_line_args, descriptor)
        
    #if we aren't extracting files, lets check that there is already
    #a file in libsvm format. If there isn't we will make one
    
    #if this file doesn't exist, we have two options
    #use the near incomplete features if the preprocessing run finished completely
    #otherwise use the nearly complete feature set
    
    if(os.path.isfile(os.path.join(command_line_args.model_path , 'X.npy'))):
        X = np.load(os.path.join(command_line_args.model_path , 'X.npy'))
        Y = np.load(os.path.join(command_line_args.model_path , 'Y.npy'))        
    else:
        X = np.load(os.path.join(command_line_args.model_path, 'X_temp.npy'))
        Y = np.load(os.path.join(command_line_args.model_path, 'Y_temp.npy'))
            
    #if we are doing sub challenge 2, add the metadata features
    if(command_line_args.sub_challenge == 2):
        print('adding metadata')
        X,Y = add_metadata_features(X,Y,command_line_args)            
        
    #now lets make an libsvm compatable file         
    dump_svmlight_file(X,Y,os.path.join(command_line_args.model_path, 'data_file_libsvm'))
        
    #lets scale the features first
    terminal_cmd(command_line_args.train_scale_string)
    
    #now features are extracted, lets train using this bad boy
    terminal_cmd(command_line_args.train_string)
    
    
    
def validate_model(command_line_args, descriptor):
    
    #if preprocessing was specified in this run (-p) than tho model will
    #have first preprocessed the data
    #may want to just extract features though, if we do, we have that ability
    if(command_line_args.extract_features):
        begin_processes(command_line_args, descriptor)
        
    #Otherwise will assume that preprocessing has already been done prior
    
    #if we are doing sub challege 2, we will need to add the metadata features to the feature array
    X = np.load(os.path.join(command_line_args.save_path, 'model_data/X.npy'))
    Y = np.load(os.path.join(command_line_args.save_path, 'model_data/Y.npy'))
    if(command_line_args.sub_challenge == 2):
        X,Y = add_metadata_features(X,Y,command_line_args)            
        
    #now lets make an libsvm compatable file         
    #so we can use libsvm
    dump_svmlight_file(X,Y,os.path.join(command_line_args.save_path, 'model_data/data_file_libsvm'))
        
    #scale the features
    terminal_cmd(command_line_args.validation_scale_string)
    
    
    #run validation
    terminal_cmd(command_line_args.validation_string)
    #now load in the validation data
    #so we can group the prediction value from each of the scans
    #to get an overall prediction value for individual breasts
    lateralities = np.load(os.path.join(command_line_args.save_path, 'model_data/lateralities.npy'))
    exams = np.load(os.path.join(command_line_args.save_path, 'model_data/exams.npy'))
    subject_ids = np.load(os.path.join(command_line_args.save_path, 'model_data/subject_ids.npy'))
    print exams
    print exams.shape
    #load in any scans that were skipped
    skipped_ids = my_pickle_load(os.path.join(command_line_args.save_path , 'model_data/skipped_ids'))
    skipped_lateralities = my_pickle_load(os.path.join(command_line_args.save_path , 'model_data/skipped_lateralities'))  
    skipped_cancer_status = my_pickle_load(os.path.join(command_line_args.save_path , 'model_data/skipped_cancer_status'))
    skipped_exam = my_pickle_load(os.path.join(command_line_args.save_path , 'model_data/skipped_exam'))
    print skipped_exam
    print len(skipped_exam)
    #load in the predicted values
    predicted = load_results(command_line_args)
    #add in the scans that were skipped, and assume they were negative (benign)
    predicted = np.append(predicted, ([0] * len(skipped_ids)))
    print np.shape(predicted)
    #append the actual data that was skipped to the real data
    lateralities = np.append(lateralities,skipped_lateralities)
    exams = np.append(exams,[item for sublist in skipped_exam for item in sublist])
    subject_ids = np.append(subject_ids,skipped_ids)
    
    print lateralities.shape
    print exams.shape
    print subject_ids.shape
    
    #load in the actual class values
    #WILL ONLY BE USEFUL IF VALIDATING ON OUR DATA
    #OTHERWISE I HAVE JUST SET THEM ALL TO ZERO :)
    actual = np.load(os.path.join(command_line_args.save_path, 'model_data/Y.npy'))
    #append skipped cancer status
    actual = np.append(actual, skipped_cancer_status)
    
    #creating a set of all the subjects used
    #set is used so we don't have repeated values
    subject_ids_set = set(subject_ids)
    
    #now will loop over all of the subjects in the validation set
    #will find scans for each breast and each examination
    #this will give us a prediction for that single breast of that patient per
    #single exam
    
    predicted_breast = []   #prediction based on individual breasts in the data set
    actual_breast = []      #actual classifier value based
                            #WILL ONLY BE USEFUL IF VALIDATING ON OUR DATA 
    actual_laterality = []  #save the laterality of this breast as well
    actual_subject_ids = [] #list that has the actual subject id's 
    
    
    for subject in subject_ids_set:
    #am going to initialise a mask of all the positions of scans for the current patient
        subject_mask = subject_ids == subject
        #now find the number of exams this patient has in the validation set
        num_exams = np.max(exams[subject_mask])
        #now iterate over all of these exams to get the data for these
        #start at 1 since the exams are not zero indexed
        for exam in range(1, num_exams+1):
            #now will loop over left and right
            for laterality in ['L', 'R']:
                #find a mask of all the scans from this patient
                #in this exam and this breast
                mask = subject_mask & (exams == exam) & (lateralities == laterality)
                #now use this to find the mean predicted score for this breast
                #but only try and do this is there is at least a single scan found in the final mask
                if(np.sum(mask) > 0):
                    #add the mean of the prediction value found from these scans to the list
                    predicted_breast.append( np.mean(predicted[mask]) )
                    actual_breast.append( np.mean(actual[mask]) )
                    actual_laterality.append(laterality)
                    actual_subject_ids.append(subject)
                    
    print predicted_breast
    #now will find the AUROC score
    print('Area Under the Curve Prediction Score = %f' %(roc_auc_score(actual_breast, predicted_breast))) 
    print('Accuracy = %f' %(metric_accuracy(actual, predicted))) 
    print('Sensitivity = %f' %(metric_sensitivity(actual_breast, predicted_breast)))
    print('Specificity = %f' %(metric_specificity(actual_breast, predicted_breast)))
    #metric_plot_roc(actual, predicted)
    #now save this as a tsv file
    #inference.to_csv('/output/predictions.tsv', sep='\t')
    out = open('./output/predictions.tsv', 'w')
    #write the headers for the predictions file
    out.write('subjectId\tlaterality\tconfidence\n')
    for row in range(0, len(actual_subject_ids)):
        out.write('%s\t' %actual_subject_ids[row])
        out.write('%s\t' %actual_laterality[row])
        out.write('%s' %predicted_breast[row])
        out.write('\n')
        
    out.close()



if __name__ == '__main__':
    #start the program timer
    program_start = timeit.default_timer()
    command_line_args = arguments(sys.argv[1:])
    
    #if we are preprocessing or validating, we will need the descriptor
    #with all of the relevant information
    #if we are just training, we shouldn't have to worry about it,
    #as we currently will have saved all of that data
    #
    #The only time we would want to redo this when training is if we are
    #going to extract features again.
    #Normally loading in this data again even if we weren't going to use it
    #wouldn't be a big deal, but when doing it as part of the challenge,
    #since there are so many scans it can take a while,
    #so don't want to do it if I don't have to
    
    descriptor = []
    if(command_line_args.preprocessing | command_line_args.validation |
       command_line_args.extract_features):
        descriptor = spreadsheet(command_line_args)
    if(command_line_args.preprocessing):
        preprocessing(command_line_args, descriptor)
    #if we want to train the model, lets start training
    if(command_line_args.training):
        train_model(command_line_args, descriptor)
    #if we want to do some validation, lets dooo it :)
    if(command_line_args.validation):
        validate_model(command_line_args, descriptor)
    print("Exiting Main Process")

#import matplotlib.pyplot as plt
import numpy as np
import os
import sys
#from IPython.core.debugger import Tracer
from scipy.io import wavfile

# Use off-the-shelf package for mel frequency spectrogram (not MFCC) for now, may write one myself at some point
# Copyright (c) 2006 Carnegie Mellon University
#
# You may copy and modify this freely under the same terms as
# Sphinx-III

"""Compute MFCC coefficients.
    
    This module provides functions for computing MFCC (mel-frequency
    cepstral coefficients) as used in the Sphinx speech recognition
    system.
    """

__author__ = "David Huggins-Daines <dhuggins@cs.cmu.edu>"
__version__ = "$Revision: 6390 $"

import numpy, numpy.fft

def mel(f):
    return 2595. * numpy.log10(1. + f / 700.)

def melinv(m):
    return 700. * (numpy.power(10., m / 2595.) - 1.)

class MFCC(object):
    def __init__(self, nfilt=40, ncep=13,
                 lowerf=133.3333, upperf=6855.4976, alpha=0.97,
                 samprate=16000, frate=160, wlen=0.0256,
                 nfft=512):
        # Store parameters
        self.lowerf = lowerf
        self.upperf = upperf
        self.nfft = nfft
        self.ncep = ncep
        self.nfilt = nfilt
        self.frate = frate
        self.fshift = float(samprate) / frate
        
        # Build Hamming window
        self.wlen = int(wlen * samprate)
        self.win = numpy.hamming(self.wlen)
        
        # Prior sample for pre-emphasis
        self.prior = 0
        self.alpha = alpha
        
        # Build mel filter matrix
        self.filters = numpy.zeros((nfft/2+1,nfilt), 'd')
        dfreq = float(samprate) / nfft
        if upperf > samprate/2:
            raise(Exception,
                  "Upper frequency %f exceeds Nyquist %f" % (upperf, samprate/2))
        melmax = mel(upperf)
        melmin = mel(lowerf)
        dmelbw = (melmax - melmin) / (nfilt + 1)
        # Filter edges, in Hz
        filt_edge = melinv(melmin + dmelbw * numpy.arange(nfilt + 2, dtype='d'))
        
        for whichfilt in range(0, nfilt):
            # Filter triangles, in DFT points
            leftfr = round(filt_edge[whichfilt] / dfreq)
            centerfr = round(filt_edge[whichfilt + 1] / dfreq)
            rightfr = round(filt_edge[whichfilt + 2] / dfreq)
            # For some reason this is calculated in Hz, though I think
            # it doesn't really matter
            fwidth = (rightfr - leftfr) * dfreq
            height = 2. / fwidth
            
            if centerfr != leftfr:
                leftslope = height / (centerfr - leftfr)
            else:
                leftslope = 0
            freq = leftfr + 1
            while freq < centerfr:
                #print('freq, which filt values:', freq, whichfilt)
                self.filters[int(freq),whichfilt] = (freq - leftfr) * leftslope
                freq = freq + 1
            if freq == centerfr: # This is always true
                self.filters[int(freq),whichfilt] = height
                freq = freq + 1
            if centerfr != rightfr:
                rightslope = height / (centerfr - rightfr)
            while freq < rightfr:
                self.filters[int(freq),whichfilt] = (freq - rightfr) * rightslope
                freq = freq + 1
                #             print("Filter %d: left %d=%f center %d=%f right %d=%f width %d" %
                #                   (whichfilt,
                #                   leftfr, leftfr*dfreq,
                #                   centerfr, centerfr*dfreq,
                #                   rightfr, rightfr*dfreq,
                #                   freq - leftfr))
                #             print self.filters[leftfr:rightfr,whichfilt]
                # Build DCT matrix
                self.s2dct = s2dctmat(nfilt, ncep, 1./nfilt)
                self.dct = dctmat(nfilt, ncep, numpy.pi/nfilt)

    def sig2s2mfc(self, sig):
        nfr = int(len(sig) / self.fshift + 1)
        mfcc = numpy.zeros((nfr, self.ncep), 'd')
        fr = 0
        while fr < nfr:
            start = round(fr * self.fshift)
            end = min(len(sig), start + self.wlen)
            frame = sig[int(start):int(end)]
            if len(frame) < self.wlen:
                frame = numpy.resize(frame,self.wlen)
                frame[self.wlen:] = 0
            mfcc[fr] = self.frame2s2mfc(frame)
            fr = fr + 1
        return mfcc

    def sig2logspec(self, sig):
        nfr = int(len(sig) / self.fshift + 1)
        mfcc = numpy.zeros((nfr, self.nfilt), 'd')
        fr = 0
        while fr < nfr:
            start = round(fr * self.fshift)
            end = min(len(sig), start + self.wlen)
            frame = sig[int(start):int(end)]
            if len(frame) < self.wlen:
                frame = numpy.resize(frame,self.wlen)
                frame[self.wlen:] = 0
            mfcc[fr] = self.frame2logspec(frame)
            fr = fr + 1
        return mfcc

    def pre_emphasis(self, frame):
        # FIXME: Do this with matrix multiplication
        outfr = numpy.empty(len(frame), 'd')
        outfr[0] = frame[0] - self.alpha * self.prior
        for i in range(1,len(frame)):
            outfr[i] = frame[i] - self.alpha * frame[i-1]
            self.prior = frame[-1]
        return outfr

    def frame2logspec(self, frame):
        frame = self.pre_emphasis(frame) * self.win
        fft = numpy.fft.rfft(frame, self.nfft)
        # Square of absolute value
        power = fft.real * fft.real + fft.imag * fft.imag
        return numpy.log(numpy.dot(power, self.filters).clip(1e-5,numpy.inf))
    
    def frame2s2mfc(self, frame):
        logspec = self.frame2logspec(frame)
        return numpy.dot(logspec, self.s2dct.T) / self.nfilt

def s2dctmat(nfilt,ncep,freqstep):
    """Return the 'legacy' not-quite-DCT matrix used by Sphinx"""
    melcos = numpy.empty((ncep, nfilt), 'double')
    for i in range(0,ncep):
        freq = numpy.pi * float(i) / nfilt
        melcos[i] = numpy.cos(freq * numpy.arange(0.5, float(nfilt)+0.5, 1.0, 'double'))
    melcos[:,0] = melcos[:,0] * 0.5
    return melcos

def logspec2s2mfc(logspec, ncep=13):
    """Convert log-power-spectrum bins to MFCC using the 'legacy'
        Sphinx transform"""
    nframes, nfilt = logspec.shape
    melcos = s2dctmat(nfilt, ncep, 1./nfilt)
    return numpy.dot(logspec, melcos.T) / nfilt

def dctmat(N,K,freqstep,orthogonalize=True):
    """Return the orthogonal DCT-II/DCT-III matrix of size NxK.
        For computing or inverting MFCCs, N is the number of
        log-power-spectrum bins while K is the number of cepstra."""
    cosmat = numpy.zeros((N, K), 'double')
    for n in range(0,N):
        for k in range(0, K):
            cosmat[n,k] = numpy.cos(freqstep * (n + 0.5) * k)
    if orthogonalize:
        cosmat[:,0] = cosmat[:,0] * 1./numpy.sqrt(2)
    return cosmat

def dct(input, K=13):
    """Convert log-power-spectrum to MFCC using the orthogonal DCT-II"""
    nframes, N = input.shape
    freqstep = numpy.pi / N
    cosmat = dctmat(N,K,freqstep)
    return numpy.dot(input, cosmat) * numpy.sqrt(2.0 / N)

def dct2(input, K=13):
    """Convert log-power-spectrum to MFCC using the normalized DCT-II"""
    nframes, N = input.shape
    freqstep = numpy.pi / N
    cosmat = dctmat(N,K,freqstep,False)
    return numpy.dot(input, cosmat) * (2.0 / N)

def idct(input, K=40):
    """Convert MFCC to log-power-spectrum using the orthogonal DCT-III"""
    nframes, N = input.shape
    freqstep = numpy.pi / K
    cosmat = dctmat(K,N,freqstep).T
    return numpy.dot(input, cosmat) * numpy.sqrt(2.0 / K)

def dct3(input, K=40):
    """Convert MFCC to log-power-spectrum using the unnormalized DCT-III"""
    nframes, N = input.shape
    freqstep = numpy.pi / K
    cosmat = dctmat(K,N,freqstep,False)
    cosmat[:,0] = cosmat[:,0] * 0.5
    return numpy.dot(input, cosmat.T)

def loaddata2(ntr, ntx, skip, captions_name, images_name):
    mfcc = MFCC()
    # This function load training and test data such that the training and test data contain the same type of images
    infofile = '../data/Flickr8k_text/Flickr8k.token.txt'
    dir_sp = '../data/flickr_audio/wavs/'
    dir_penult = '../data/vgg_flickr8k_nnet_penults/'

    # Load one image at a time and use the first three captions as the training set and the last two captions as the test set, load the images and speech vectors, store them separately in two lists for both training and test set
    captions_tr = []
    im_tr = []
    nrep_tr = 3
    
    captions_tx = []
    im_tx = []
    nrep_tx = 2
    Leq = 1024
    count_tr = 0
    count_tx = 0
    count = 0
    
    print('Begin to load data ...')
    with open(infofile, 'r') as f:
        for i in range(skip):
            cur_info = f.readline()
        
        while not count_tr == ntr and not count_tx == ntx and not count == ntr + ntx:
            # Load the filenames of the audio caption files and the vgg16 feature files
            
            for k in range(5):
                count = count + 1
                cur_info = f.readline()
                cur_info_parts = cur_info.rstrip().split()
                im_name_raw = cur_info_parts[0]
                im_name_parts = im_name_raw.split('#')
                im_name = im_name_parts[0]
                im_id_raw = im_name.split('.')

                sp_name = im_id_raw[0] + '_' + str(k) + '.wav'
                try:
                    caption_info = wavfile.read(dir_sp+sp_name)
                except:
                    continue
                caption_time = caption_info[1]
                # Covert the audio into spectrogram
                caption = mfcc.sig2logspec(caption_time)
                # Transpose the caption data
                #if caption.shape[0] > caption.shape[1] and caption.shape[1] == 40:
                #    caption = np.transpose(caption)
                # Equalize the length
                if caption.shape[1] < Leq:
                    nframes = caption.shape[1]
                    nmf = caption.shape[0]
                    #print('240:', nframes, (Leq-nframes)/2)
                    caption_new = np.zeros((nmf, Leq))
                    caption_new[:, int(round((Leq-nframes)/2)):int(round((Leq-nframes)/2)+nframes)] = caption
                else:
                    if caption.shape[1] > Leq:
                        nframes = caption.shape[1]
                        nmf = caption.shape[0]
                        caption_new = np.zeros((nmf, Leq))
                        caption_new = caption[:, int(round((nframes-Leq)/2)):int(round((nframes-Leq)/2)+Leq)]
                        #print('248:', caption_new)
                data = np.load(dir_penult+im_id_raw[0]+'.npz')
                cur_penult = data['arr_0']
                #im_tr.append(cur_penult)
                
                if k < 3:
                    #if count_tr == ntr:
                    #    break
                    count_tr = count_tr + 1
                    captions_tr.append(caption_new)
                    im_tr.append(cur_penult)
                    if count_tr%10:
                        print('Finish loading', 100*count_tr/ntr, 'percent of training data')
                else:
                    #if count_tx == ntx:
                    #    break
                    count_tx = count_tx + 1
                    captions_tx.append(caption_new)
                    im_tx.append(cur_penult)
                    
                    if count_tx%10:
                        print('Finish loading', 100*count_tx/ntx, 'percent of test data')


    # Save the speech lists in one .npz file and save the image lists in another .npz file
    captions_tr = np.array(captions_tr)
    im_tr = np.array(im_tr)
    captions_tx = np.array(captions_tx)
    im_tx = np.array(im_tx)
    print('Number of train:', captions_tr.shape[0])
    print('Number of test:', captions_tx.shape[0])
    np.savez(captions_name, captions_tr, captions_tx)
    np.savez(images_name, im_tr, im_tx)
    return captions_tr, captions_tx, im_tr, im_tx




def loaddata(ntr, ntx, skip, captions_name, images_name):
    #print('ntr:', ntr)
    mfcc = MFCC()
    dir_info = '../data/flickr_audio/'
    filename_info = 'wav2capt.txt'
    
    dir_sp = '../data/flickr_audio/wavs/'
    dir_penult = '../data/vgg_flickr8k_nnet_penults/'
    
    captions_tr = []
    im_tr = []
    captions_tx = []
    im_tx = []
    Leq = 1024
    with open(dir_info+filename_info, 'r') as f:
        for _ in xrange(skip):
            next(f)
        #tmp = f.readline()
        i = 0
        for cur_info in f:
            if i == ntr:
                break
            i = i +1
            # Load the filenames of the audio caption files and the vgg16 feature files
            #cur_info = f.readline()
            cur_info_parts = cur_info.rstrip().split()
            sp_name = cur_info_parts[0]
            print(sp_name)
            try:
                caption_info = wavfile.read(dir_sp+sp_name)
                caption_time = caption_info[1]
                # Covert the audio into spectrogram
                caption = np.transpose(mfcc.sig2logspec(caption_time))
            except:
                continue
            # Transpose the caption data
            #if caption.shape[0] > caption.shape[1]:
            #    caption = np.transpose(caption)
            
            # Equalize the length
            if caption.shape[1] < Leq:
                nframes = caption.shape[1]
                nmf = caption.shape[0]
                #print('240:', nframes, (Leq-nframes)/2)
                caption_new = np.zeros((nmf, Leq))
                caption_new[:, int(round((Leq-nframes)/2)):int(round((Leq-nframes)/2)+nframes)] = caption
            else:
                if caption.shape[1] > Leq:
                    nframes = caption.shape[1]
                    nmf = caption.shape[0]
                    caption_new = np.zeros((nmf, Leq))
                    caption_new = caption[:, int(round((nframes-Leq)/2)):int(round((nframes-Leq)/2)+Leq)]
            #print('248:', caption_new.shape)
            captions_tr.append(caption_new)
            # Remove the .jpg# at the end of the file to .npz format, which is used to store vgg16 feature
            im_name_raw = cur_info_parts[1]
            im_name_parts = im_name_raw.split('.')
            im_name = im_name_parts[0]
            # Load the softmax activations of the images, store them into an array
            data = np.load(dir_penult+im_name+'.npz')
            cur_penult = data['arr_0']
            im_tr.append(cur_penult)
            if i%10 == 0:
                #print(i)
                print('Finish loading', 100*i/ntr, 'percent of training data')
        captions_tr = np.array(captions_tr)
        im_tr = np.array(im_tr)
        #np.savez('captions_tr.npz', captions_tr)
        #np.savez('images_tr.npz', im_tr)
        j = 0
        # Code for loading test data is wrong, but not used
        for cur_info in f:
            if j == ntx:
                break
            j = j + 1
            # Load the image names and the image captions, break the captions into words and store in a list
            cur_info_parts = cur_info.rstrip().split()
            sp_name = cur_info_parts[0]
            try:
                caption_info = wavfile.read(dir_sp+sp_name)
                caption_time = caption_info[1]
                caption = mfcc.sig2logspec(caption_time)
            except:
                continue
            # Transpose the data
            #if caption.shape[0] > caption.shape[1]:
            #    caption = np.transpose(caption)
            # Equalize the length
            if caption.shape[1] < Leq:
                nframes = caption.shape[1]
                nmf = caption.shape[0]
                caption_new = np.zeros((nmf, Leq))
                #print('274:', nframes, (Leq-nframes)/2)
                caption_new[:, int((Leq-nframes)/2:(Leq-nframes)/2+nframes)] = caption
            else:
                if caption.shape[1] > Leq:
                    nframes = caption.shape[1]
                    nmf = caption.shape[0]
                    caption_new = np.zeros((nmf, Leq))
                    caption_new = caption[:, int((nframes-Leq)/2):int((nframes-Leq)/2+Leq)]
            captions_tx.append(caption_new)
            # Remove the .jpg# at the end of the file to the format of vgg16 feature file
            im_name_raw = cur_info_parts[1]
            im_name_parts = im_name_raw.split('.')
            #len_im_name = len(im_name_parts[0])
            # Remove the caption number
            im_name = im_name_parts[0]
            # Load the softmax activations of the images, store them into an array
            data = np.load(dir_penult+im_name+'.npz')
            cur_penult = data['arr_0']
            im_tx.append(cur_penult)
            if j % 100 == 0:
                print('Finish loading', 100*j/ntx, 'percent of test data')
        captions_tx = np.array(captions_tx)
        im_tx = np.array(im_tx)
    np.savez(captions_name, captions_tr, captions_tx)
    np.savez(images_name, im_tr, im_tx)
    #np.savez('captions.npz', captions_tr, captions_tx)
    #np.savez('images.npz', im_tr, im_tx)
    return captions_tr, captions_tx, im_tr, im_tx

ntr = int(sys.argv[1])
ntx = int(sys.argv[2])
skip = int(sys.argv[3])
captions_name = 'captions.npz'
images_name = 'images.npz'
if len(sys.argv) >= 6:
    captions_name = sys.argv[4]
    images_name = sys.argv[5]
print('ntr:', ntr)
print('ntx:', ntx)
print('skip:', skip)
captions_tr, captions_tx, im_tr, im_tx = loaddata(ntr, ntx, skip, captions_name, images_name)


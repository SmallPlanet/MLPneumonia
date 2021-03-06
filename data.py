# script responsible for generating audio sample of specific sounds waves.  Supports
# exporting those samples to WAV files for confirmation.

from __future__ import division

import csv
import pydicom
import numpy as np
import os
import random
import os.path
from model import IMG_SIZE
from model import IMG_SUBDIVIDE
from PIL import Image,ImageDraw

kPatientID = 0
kBoundsX = 1
kBoundsY = 2
kBoundsWidth = 3
kBoundsHeight = 4
kTarget = 5

kMaxImageOffset = 10
	
class DCMGenerator():
	
	def __init__(self,directory,labelsFile):
		self.directory = directory
		self.ignoreCaches = False
		self.labelsFile = labelsFile
		self.labelsInfo = []
		
		# load in all of the label info if it exists
		if labelsFile is not None:
			with open(labelsFile) as csv_file:
				self.labelsInfo = list(csv.reader(csv_file))
				self.labelsInfo.pop(0)
		else:
			# generate from file names in directory...
			self.labelsInfo = []
			for file in os.listdir(self.directory):
			    if file.endswith(".dcm"):
					patient = [os.path.splitext(file)[0], 0, 0, 0, 0, 0]
					self.labelsInfo.append(patient)
					
			
	def simpleImageAugment(self,imageData,xOff,yOff):
		# very simple slide x/y image augmentation
		imageData = np.roll(imageData, int(xOff), axis=1)
		imageData = np.roll(imageData, int(yOff), axis=0)
		return imageData
		
	
	def loadImageForPatientId(self,patient):
		imageData = None
		
		patientId = patient[kPatientID]
		
		# first check if a cached numpy array file already exists
		cachedFilePath = self.directory + "/" + patientId + ".npy"
		dcmFilePath = self.directory + "/" + patientId + ".dcm"
		
		if self.ignoreCaches == True or os.path.isfile(cachedFilePath) == False:
			# load the DCM and process it, saving the resulting numpy array to file
			dcmData = pydicom.read_file(dcmFilePath)
			imageData = dcmData.pixel_array
			
			# preprocess the image (reshape and normalize)
			# 1. resize it to IMG_SIZE (ie downsample)
			# 2. convert to float32
			# 3. reshape to greyscale
			# 4. normalize
			image = Image.fromarray(imageData).convert("RGB")
						
			image = image.resize((IMG_SIZE[0],IMG_SIZE[1]), Image.ANTIALIAS)
			image = image.convert('L')
			imageData = np.array(image).astype('float32').reshape(IMG_SIZE[0],IMG_SIZE[1],IMG_SIZE[2]) / 255
			
			print("caching image: %s" % cachedFilePath)
			np.save(cachedFilePath, imageData)
		
		if imageData is None and os.path.isfile(cachedFilePath) == True:
			imageData = np.load(cachedFilePath)
				
		return imageData
		
	
	def generateImages(self,num,augment,positiveSplit):
		
		localLabelsInfo = self.labelsInfo[:]
		
		randomSelection = True
		if num <= 0:
			num = len(localLabelsInfo)
			randomSelection = False
		
		input = np.zeros((num,IMG_SIZE[1],IMG_SIZE[0],IMG_SIZE[2]), dtype='float32')
		output = np.zeros((num,IMG_SUBDIVIDE+IMG_SUBDIVIDE), dtype='float32')
		
		random.shuffle(localLabelsInfo)
		
		patientIds = []
		
		numPositive = 0
		numNegative = 0
		
		for i in range(0,num):
			
			if randomSelection:
				attempts = 10000
				while attempts > 0:
					patient = random.choice(localLabelsInfo)
					
					if numPositive <= (numNegative+numPositive)*positiveSplit and patient[kTarget] == "1":
						numPositive += 1
						break
					if numPositive > (numNegative+numPositive)*positiveSplit and patient[kTarget] == "0":
						numNegative += 1
						break
					
					attempts -= 1
			else:
				patient = localLabelsInfo[i]
			
			if num < len(localLabelsInfo):
				localLabelsInfo.remove(patient)
			
			patientIds.append(patient[kPatientID])
			
			input2,output2 = self.generateImagesForPatient(patient[kPatientID],augment)
			
			np.copyto(input[i],input2[0])
			np.copyto(output[i],output2[0])
		
		if randomSelection:
			print(numPositive, numNegative)
							
		return input,output,patientIds
	
	def generateImagesForPatient(self,patientID,augment=True):
		
		localPatientInfo = []
		for i in range(0,len(self.labelsInfo)):
			patient = self.labelsInfo[i]
			if patient[kPatientID] == patientID:
				localPatientInfo.append(patient)

		
		input = np.zeros((1,IMG_SIZE[1],IMG_SIZE[0],IMG_SIZE[2]), dtype='float32')
		output = np.zeros((1,IMG_SUBDIVIDE+IMG_SUBDIVIDE), dtype='float32')
		
		localPatient = localPatientInfo[0]
		
		xOffForImage = int(random.random() * (kMaxImageOffset*2) - kMaxImageOffset)
		yOffForImage = int(random.random() * (kMaxImageOffset*2) - kMaxImageOffset)
		
		if augment == False:
			xOffForImage = 0
			yOffForImage = 0
						
		imageData = self.loadImageForPatientId(localPatient)
		imageData = self.simpleImageAugment(imageData,xOffForImage,yOffForImage)
		np.copyto(input[0], imageData)
	
		if localPatient[kTarget] == "1":
			# note: we may have multiple data lines per patient, so we want to
			# combine their outputs such that there is only one combined training sample
			for patient in localPatientInfo:
				xOffForBounds = xOffForImage * (1024 / IMG_SIZE[0])
				yOffForBounds = yOffForImage * (1024 / IMG_SIZE[1])
			
				xmin = float(patient[kBoundsX]) + xOffForBounds
				ymin = float(patient[kBoundsY]) + yOffForBounds
				xmax = xmin + float(patient[kBoundsWidth])
				ymax = ymin + float(patient[kBoundsHeight])
		
				# Note: the canvas the bounds are in is 1024x1024
				xdelta = (1024 / IMG_SUBDIVIDE)
				ydelta = (1024 / IMG_SUBDIVIDE)
				for x in range(0, IMG_SUBDIVIDE):
					for y in range(0, IMG_SUBDIVIDE):
						xValue = x * xdelta
						yValue = y * ydelta
						if xValue+xdelta >= xmin and xValue <= xmax:
							output[0][x] = 1
						if yValue+ydelta >= ymin and yValue <= ymax:
							output[0][IMG_SUBDIVIDE+y] = 1
				
		return input,output
	
	def generatePredictionImages(self):
		
		num = len(self.labelsInfo)
				
		input = np.zeros((num,IMG_SIZE[1],IMG_SIZE[0],IMG_SIZE[2]), dtype='float32')
				
		for i in range(0,num):
			patient = self.labelsInfo[i]
			imageData = self.loadImageForPatientId(patient)
			np.copyto(input[i], imageData)
										
		return self.labelsInfo,input
	
	def convertOutputToString(self,output):
		for x in range(0,IMG_SUBDIVIDE):
			for y in range(0,IMG_SUBDIVIDE):
				if output[x] >= 0.5 and output[IMG_SUBDIVIDE+y] >= 0.5:
					return 1
		return 0
	
	
	def identifyPeaksForAxis(self,output):
		IMG_SUBDIVIDE = int(len(output))
		xdelta = 1.0 / IMG_SUBDIVIDE
		ydelta = 1.0 / IMG_SUBDIVIDE
		
		peak_indentity = np.zeros((IMG_SUBDIVIDE), dtype='float32')
		minPeakSize = 3
		
		peakIdx = 0
		x = 0
		while x < IMG_SUBDIVIDE:
			xValue = (x*xdelta)
			
			# step forward until we find the first peak
			if output[x] >= 0.5:
				# ensure this peak is large enough (ignore little peaks)
				isPeak = False
				for x2 in range(x,IMG_SUBDIVIDE):
					if output[x2] < 0.5:
						if x2 - x > minPeakSize:
							isPeak = True
				
				# peak identified, fill it out
				if isPeak:
					peakIdx += 1
					for x2 in range(x,IMG_SUBDIVIDE):
						if output[x2] >= 0.5:
							peak_indentity[x2] = peakIdx
						else:
							break
					x = x2
			x += 1
		return peak_indentity,peakIdx
	
	def coordinatesFromOutput(self,output,size):
		# 1. run through X and Y outputs and identify peaks (0 for not in peak, increasing numeral of different peak)
		# 2. run through X and Y output values, and identify new bounds based on peak index
		IMG_SUBDIVIDE = int(len(output)/2)
		xdelta = 1.0 / IMG_SUBDIVIDE
		ydelta = 1.0 / IMG_SUBDIVIDE
		
		x_output = output[0:IMG_SUBDIVIDE]
		y_output = output[IMG_SUBDIVIDE:]
		
		x_peaks,num_x_peaks = self.identifyPeaksForAxis(x_output)
		y_peaks,num_y_peaks = self.identifyPeaksForAxis(y_output)
		
		'''
		print("x axis")
		print(x_output)
		print(x_peaks)
		print("-----------------------")
		print("y axis")
		print(y_output)
		print(y_peaks)
		print("-----------------------")
		'''
		
		boxes = []
		
		for peakIdx in range(1,num_x_peaks+1):
		
			xmin = 1.0
			xmax = 0.0
			ymin = 1.0
			ymax = 0.0
	
			for x in range(0,IMG_SUBDIVIDE):
				for y in range(0,IMG_SUBDIVIDE):
					xValue = (x*xdelta)
					yValue = (y*ydelta)
					
					if x_peaks[x] == peakIdx:
						if output[x] >= 0.5 and output[IMG_SUBDIVIDE+y] >= 0.5:
							if xValue < xmin:
								xmin = xValue
							if xValue > xmax:
								xmax = xValue
							if yValue < ymin:
								ymin = yValue
							if yValue > ymax:
								ymax = yValue
			
			#only boxes with decent width or height are counted
			box = (int(xmin*size[1]),int(ymin*size[0]),int(xmax*size[1]),int(ymax*size[0]))
			if box[2] - box[0] > 10 and box[3] - box[1] > 10:
				boxes.append(box)
				
		return boxes
	
			

if __name__ == '__main__':
		
	#generator = DCMGenerator("data/stage_1_train_images", "data/stage_1_train_images.csv")
	generator = DCMGenerator("data/stage_1_train_images", "data/stage_1_train_images.csv")	
	generator.ignoreCaches = True
	
	input,output,patientIds = generator.generateImages(2,True,0.5)
	
	for i in range(0,len(input)):
				
		sourceImg = Image.fromarray(input[i].reshape(IMG_SIZE[0],IMG_SIZE[1]) * 255.0).convert("RGB")
		
		draw = ImageDraw.Draw(sourceImg)
		
		boxes = generator.coordinatesFromOutput(output[i],IMG_SIZE)
		for box in boxes:
			draw.rectangle(box, outline="white")
		
		sourceImg.save('/tmp/scan_%d_%s.png' % (i, generator.convertOutputToString(output[i])))
	
	
# This Python file uses the following encoding: utf-8
#####################################################
#            __ __             _                 _
#     ____  / // /_   ______  (_)_______  __  __(_)
#    / __ \/ // /| | / / __ \/ / ___/ _ \/ / / / /
#   / /_/ /__  __/ |/ / /_/ / / /__/  __/ /_/ / /
#  / .___/  /_/  |___/\____/_/\___/\___/\__,_/_/
# /_/
#
#####################################################
# Title:        p4voiceui
# Version:      8.7
# Description:  Voice activation of docker container deployment system
# Author:       Jonas Werner
#####################################################
import p4security
import datetime, time
import boto3
import os
import uuid
import pyaudio
import wave
import RPi.GPIO as GPIO
import re
import time
import argparse
from multiprocessing import Process
import requests

from luma.led_matrix.device import max7219
from luma.core.interface.serial import spi, noop
from luma.core.render import canvas
from luma.core.virtual import viewport
from luma.core.legacy import text, show_message
from luma.core.legacy.font import proportional, CP437_FONT, TINY_FONT, SINCLAIR_FONT, LCD_FONT


AWS_ACCESS_KEY_ID       = os.environ["AWS_ACCESS_KEY_ID"]
AWS_SECRET_ACCESS_KEY   = os.environ["AWS_SECRET_ACCESS_KEY"]
AWS_DEFAULT_REGION      = os.environ["AWS_DEFAULT_REGION"]

CHUNK 			= 1024
FORMAT 			= pyaudio.paInt16
CHANNELS 		= 1
RATE 			= 16000
RECORD_SECONDS 		= 3
WAVE_OUTPUT_FILENAME 	= "voice.wav"

# Endpoints
urlDockerLocal = "192.168.2.93:5100/api/v1/docker"

# GPIO pin setup:
LedPin 		= 11    # pin11 --- led
BtnPin 		= 12    # pin12 --- button
servoPin 	= 23 	# pin23 --- camera servo

# RGB LED setup:
colors = [0xFF0000, 0x00FF00, 0x0000FF, 0xFFFF00, 0xFF00FF, 0x00FFFF]
pins = {'pin_R':31, 'pin_G':32, 'pin_B':33}  # pins is a dict

GPIO.setmode(GPIO.BOARD)       # Numbers GPIOs by physical location
for i in pins:
	GPIO.setup(pins[i], GPIO.OUT)   # Set pins' mode is output
	GPIO.output(pins[i], GPIO.LOW) # Set pins to high(+3.3V) to off led

p_R = GPIO.PWM(pins['pin_R'], 2000)  # set Frequece to 2KHz
p_G = GPIO.PWM(pins['pin_G'], 2000)
p_B = GPIO.PWM(pins['pin_B'], 5000)

p_R.start(0)      # Initial duty Cycle = 0(leds off)
p_G.start(0)
p_B.start(0)


def setup():
	GPIO.setmode(GPIO.BOARD)       # Numbers GPIOs by physical location
	GPIO.setup(LedPin, GPIO.OUT)   # Set LedPin's mode is output
	GPIO.setup(BtnPin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)    # Set BtnPin's mode is input, and pull up to high level(3.3V)
	GPIO.output(LedPin, GPIO.HIGH) # Set LedPin high(+3.3V) to make led off
	GPIO.setup(servoPIN, GPIO.OUT)

def servoControl(angle):
	p = GPIO.PWM(servoPin, 50) # 50Hz PWM duty cycle
	p.start(2.5) # Initialize
	p.ChangeDutyCycle(angle)


def record_request(WAVE_OUTPUT_FILENAME):

	p = pyaudio.PyAudio()

	stream = p.open(format=FORMAT,
	                channels=CHANNELS,
	                rate=RATE,
	                input=True,
	                frames_per_buffer=CHUNK)

	print("*** listening ***")
	GPIO.output(LedPin, GPIO.HIGH)

	frames = []

	for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
	    data = stream.read(CHUNK)
	    frames.append(data)

	print("*** recording stopped ***")
	GPIO.output(LedPin, GPIO.LOW)

	stream.stop_stream()
	stream.close()
	p.terminate()

	wf = wave.open(WAVE_OUTPUT_FILENAME, 'wb')
	wf.setnchannels(CHANNELS)
	wf.setsampwidth(p.get_sample_size(FORMAT))
	wf.setframerate(RATE)
	wf.writeframes(b''.join(frames))
	wf.close()

	path = os.path.abspath(WAVE_OUTPUT_FILENAME)

	return path

def play_sound(waveFile):
	os.system("mpg321 " + waveFile)


def callLex(path, user):
	recording = open(path, 'rb')
	client = boto3.client('lex-runtime',
				aws_access_key_id	= AWS_ACCESS_KEY_ID,
				aws_secret_access_key	= AWS_SECRET_ACCESS_KEY,
				region_name		= AWS_DEFAULT_REGION)

	r = client.post_content(	botName		='voiceui',
					botAlias	='$LATEST',
					userId		=user,
					contentType	='audio/l16; rate=16000; channels=1',
					accept		="audio/mpeg",
					inputStream	=recording
							)
	print(r)

	audio_stream = r['audioStream'].read()
	r['audioStream'].close()
	f = wave.open("wavefile.wav", 'wb')
	f.setnchannels(2)
	f.setsampwidth(2)
	f.setframerate(16000)
	f.setnframes(0)
	f.writeframesraw(audio_stream)
	f.close()

	return r



def deployContainer(containerType, containerName):
	print("########### Deploying: %s with name: %s" % (containerType, containerName))

	if "grafana" in containerType.lower():
		portInt 	= "3000"
		portExt 	= "3000"
		name    	= containerName
		dockerImage = "grafana/grafana:latest"
		mode    	= "detached"
	elif "influx" in containerType.lower():
		portInt 	= "1880"
		portExt 	= "1880"
		name    	= containerName
		dockerImage = "influxdb:latest"
		mode    	= "detached"

	url = "http://%s/run?image=%s&name=%s&mode=%s&portInt=%s&portExt=%s" % (urlDockerLocal, dockerImage, name, mode, portInt, portExt)
	res = requests.get(url)

	results = res.text



def showMessage(lexStatus):
    n = 4
    cascaded = 1
    block_orientation = -90
    rotate = 0
    inreverse = 0

    # create matrix device
    serial = spi(port=0, device=0, gpio=noop())
    device = max7219(serial, cascaded=n or 1, block_orientation=block_orientation,
                     rotate=rotate or 0, blocks_arranged_in_reverse_order=inreverse)
    print("Created device")

    msg = lexStatus

    msg = re.sub(" +", " ", msg)
    print(msg)
    show_message(device, msg, fill="white", font=proportional(LCD_FONT), scroll_delay=0.02)



def main():

	user = uuid.uuid4().hex

	# GPIO.setmode(GPIO.BCM)
	GPIO.setwarnings(False)
	# GPIO.setup(17,GPIO.OUT)
	GPIO.setup(11,GPIO.OUT)

	status = ""

	while status != "Fulfilled":

		path = record_request(WAVE_OUTPUT_FILENAME)

		if path is None:
			print('Nothing recorded')
			return

		lexData = callLex(path, user)

		print("############### ORDER STATUS: %s", lexData[u'dialogState'])
		status = lexData[u'dialogState']

		# showMessage(status)

		p = Process(target=showMessage, args=(status,))
		# Setting daemon to true so we don't have to wait for the process to join
		p.daemon = True
		p.start()

		if status == "Fulfilled":
			containerType = lexData[u'slots'][u'containerType']
			containerName = lexData[u'slots'][u'containerName']
			deployContainer(containerType, containerName)
			rgbLedExecute()
		else:
			play_sound("wavefile.wav")


		# clean up temp files
		os.remove("wavefile.wav")
		os.remove(path)


def map(x, in_min, in_max, out_min, out_max):
	return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min

def setColor(col):   # For example : col = 0x112233
	R_val = (col & 0x110000) >> 16
	G_val = (col & 0x001100) >> 8
	B_val = (col & 0x000011) >> 0

	R_val = map(R_val, 0, 255, 0, 100)
	G_val = map(G_val, 0, 255, 0, 100)
	B_val = map(B_val, 0, 255, 0, 100)

	p_R.ChangeDutyCycle(R_val)     # Change duty cycle
	p_G.ChangeDutyCycle(G_val)
	p_B.ChangeDutyCycle(B_val)


def rgbLedExecute():
	try:
		# while True:
		for col in colors:
			setColor(col)
			time.sleep(0.5)
	except KeyboardInterrupt:
		p_R.stop()
		p_G.stop()
		p_B.stop()
		for i in pins:
			GPIO.output(pins[i], GPIO.HIGH)    # Turn off all leds
		GPIO.cleanup()

def personCheck():
	# Verify that system is operated by a person
	now = datetime.datetime.now()
	photoTime = now.strftime("%Y-%m-%d_%H-%M-%S")
	filename = [photoTime + ".jpeg"]
	# Take photo of user and send to S3
	p4security.takePhoto(filename)
	filename = filename[0]
	p4security.s3Upload(filename)
	# Wait for Lambda, Rekognition and DynamoDB
	time.sleep(3)
	# Check if person is present and the Rekognition confidence
	table = p4security.getDynamoDbInfo(filename)
	confidence = p4security.findPerson(table)

	os.remove(filename)

	return confidence


def speak(text):
	polly_client = boto3.Session(
				aws_access_key_id	= AWS_ACCESS_KEY_ID,
				aws_secret_access_key	= AWS_SECRET_ACCESS_KEY,
				region_name		= AWS_DEFAULT_REGION).client('polly')

	response = polly_client.synthesize_speech(
				VoiceId		= 'Joanna',
                		OutputFormat	= 'mp3',
                		Text 		= text)

	file = open('pollyOutput.mp3', 'wb')
	file.write(response['AudioStream'].read())
	file.close()

	play_sound("pollyOutput.mp3")
	os.remove("pollyOutput.mp3")



def loop():
	while True:
		if GPIO.input(BtnPin) == GPIO.LOW: # Check whether the button is pressed or not.
			time.sleep(0.2)
			if GPIO.input(BtnPin) == GPIO.LOW:
				main()
				print("Script triggered")
			while(not not GPIO.input(BtnPin)):
				pass

def destroy():
	GPIO.output(LedPin, GPIO.HIGH)     # led off
	GPIO.cleanup()


if __name__ == '__main__':
	setup()
	# rgbLedSetup()
	GPIO.output(LedPin, GPIO.LOW)

	# Check if person present
	confidence = personCheck()

	if confidence > 90:
		speak("System active")
		try:
			loop()
		except KeyboardInterrupt:  # When 'Ctrl+C' is pressed, the child program destroy() will be  executed.
			destroy()
	else:
		print("System not being operated by a human.\nAborting.")

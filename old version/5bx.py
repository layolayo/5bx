#!/usr/bin python
#------------------------------------------------------
# 5bx.py
# Created by Matthew Hudson
#------------------------------------------------------

import apsw
import string
import time
import sys

global profileId
        
class profiles:
    def __init__(self):
        global connection
        global cursor
        self.totalcount = 0
        connection = apsw.Connection("profiles.db3")
        cursor = connection.cursor()

    def PrintAllProfiles(self):
        sql = 'SELECT COUNT(name) from Profiles'
        for x in cursor.execute(sql):
            if x[0] != 0:
                print '%s %s %s %s' %('ID'.ljust(3),'Name'.ljust(20),'Age'.center(3),'Level'.ljust(5))
                sql = 'SELECT * FROM Profiles'
                cntr = 0
                for x in cursor.execute(sql):
                    cntr += 1
                    print '%s %s %s %s' %(str(x[0]).center(3),x[1].ljust(20),str(calculate_age(x[2])).rjust(3),exer.GetLevel(x[3]).center(5))
                print ''
                self.totalcount = cntr

    def CreateNew(self):
            profileName = ''
            profileDob = ''
            profileLevel = ''

            #Get Profile Name
            response = raw_input('Enter Name (Blank line to exit) -> ')
            if response != '' :  # continue
                if string.find(response,"'"):
                    profileName = response.replace("'","\'")
                else:
                    profileName = response
                print ''

                # Get Date of Birth
                loop = True
                while loop == True:
                    response = raw_input('Enter Date of Birth for %s (dd/mm/yyyy) -> ' % (profileName))
                    try:
                        born = time.strptime(response, '%d/%m/%Y')[:3]
                        profileDob = response
                        loop = False
                    except:
                        print 'Error in Date entered \n'
                print ''

                # Get Current Fitness Level
                print 'How fit are you at the moment?'
                print '------------------------------'
                print '1) Have done no exercise at all in last 6 months'
                print '2) Exercised a little about a month ago'
                print '3) A bit of a dog walker'
                print '4) Sporadic exercise - 10-20 mins 1 or 2 times a week'
                print '5) Regular exercise - 10-20 mins 3 or 4 times a week'
                print '6) Fit as a flea - 30-60 mins 4 or 5 times a week'
                print ''
                # Get and Check response is Valid
                loop = True
                while loop == True:
                    try:
                        response = int(raw_input('Enter current fitness level to set up calibration -> '))
                        if response < 1 or response > 6:
                            print 'Invalid value - try again'
                        else:
                            if response <= 2: profileLevel = 1
                            elif response <= 4: profileLevel = 13
                            else: profileLevel = 25
                            loop = False
                    except ValueError:
                        print 'Unrecognised command - try again'

                print '~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~'
                print "Here's what we have so far"
                print "Name: %s" % profileName
                print "DoB: %s - age %d" % (profileDob, calculate_age(profileDob))
                print "Level: %s" % exer.GetLevel(profileLevel)
                print '~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~'

                response = raw_input("OK to save? (Y/n) -> ")
                if string.upper(response) != 'N':
                    # Write the Profile Record
                    sql = 'INSERT INTO Profiles (name,dob,level,calibrate) VALUES ("%s","%s",%d,1)' %(profileName,profileDob,profileLevel)
                    cursor.execute(sql)

                    # Prompt the user that we are done
                    print 'Done'
                else:
                    print 'Save aborted'
                    
    def DeleteProfile(self,which):
        resp = raw_input('Are You SURE you want to DELETE this profile? (y/N) -> ')
        if string.upper(resp) == 'Y':
            sql = "DELETE FROM Profiles WHERE id = %s" % str(which)
            cursor.execute(sql)
            print "Profile information DELETED"
        else:
            print "Delete Aborted - Returning to menu"

    def GetData(self,profid):
        sql = 'SELECT * FROM Profiles WHERE id = %d' % profid
        return cursor.execute(sql)
        
class exercises:
    def __init__(self):
        global connectionEx
        global cursorEx
        self.totalcount = 0
        connectionEx = apsw.Connection("exercises.db3")
        cursorEx = connectionEx.cursor()

    def GetLevel(self,levelid):
        sql = 'SELECT * FROM ExerciseTimes WHERE id = %d' % levelid
        for x in cursorEx.execute(sql): return str(x[1]) + get_level(x[2])

    def GetInstructions(self,chart,exercise):
        sql = 'SELECT * FROM Instructions WHERE chart = %d and exercise = %d' % (chart,exercise)
        for x in cursorEx.execute(sql): return x[3]     

    def GetCalLevel(self,chart,exercise,reps):
        sql = 'SELECT MAX(level) FROM ExerciseTimes WHERE chart = %d and ex%d <= %d' % (chart, exercise, reps)
        for x in cursorEx.execute(sql): return str(x[0])
        
    def Calibrate(self,profid):
        # Do calibration
        calibrate = []
        levels = 0
        for x in prof.GetData(profid):
            chart = exer.GetLevel(x[3])[0]
        for x in range(1,6):
            if x == 1 : time = 2
            elif x == 5 : time = 6
            else : time = 1
            exer.PerformCalibration(chart,x,time)
            response = raw_input('\n\nHow many repetitions did you do? -> ')
            calibrate.append(int(response))
        cnt = 1
        for i in calibrate:
            levels += int(exer.GetCalLevel(int(chart),int(cnt),int(i)))
            cnt += 1
        print levels/5
        
    def PerformCalibration(self,chart,exercise,e_time):
        print '\n\nPlease do the following exercise at a comfortable pace, you have %d minute(s).\nCount the number of repetitions.' % e_time
        print '\nExercise %d \n----------' % exercise
        print exer.GetInstructions(int(chart),exercise)      
        raw_input('\nPress a key to start the exercise - >')
        print '0m0s',
##        start = time.time()
##        loop = True
##        while loop == True:
##            elapsed = int(round(time.time() - start))
##            sys.stdout.write('\r' + str(abs(elapsed/60)) + 'm' + str(elapsed - (abs(elapsed/60)*60)) + 's ',)
##            sys.stdout.flush()
##            if elapsed > e_time * 60: loop = False
##            else: time.sleep(1)

    def Go(self,profid):
        print 'Doing Exercises...'

def calculate_age(birth):
    try:
        born = time.strptime(birth, '%d/%m/%Y')[:3]
        date = time.localtime()[:3]
        return int(float('%04d.%02d%02d' % (date)) - float('%04d.%02d%02d' % (born)))
    except:
        print 'A date error occured while processing your entry...\n'

def get_level(level):
    if level == 1:
        return 'D-'
    if level == 2:
        return 'D'
    if level == 3:
        return 'D+'
    if level == 4:
        return 'C-'
    if level == 5:
        return 'C'
    if level == 6:
        return 'C+'
    if level == 7:
        return 'B-'
    if level == 8:
        return 'B'
    if level == 9:
        return 'B+'
    if level == 10:
        return 'A-'
    if level == 11:
        return 'A'
    if level == 12:
        return 'A+'
    
def menu():
    global prof
    global exer
    prof = profiles() #Initialise the profiles
    exer = exercises() #Initalise the exercises
    
    loop = True
    while loop == True:
        print ''
        print '==================================================='
        print '              5BX TRAINING PROGRAMME'
        print '==================================================='
        prof.PrintAllProfiles()
        print ' C - Create New Profile'
        print ' D - Delete Profile'
        print ' X - Exit'
        print '==================================================='
        response = raw_input('Choose ID or another selection -> ')
        if response.upper() == 'X': # Exit Program
            print 'Goodbye'
            loop = False
        elif response.upper() == 'C': # Create New Profile
            prof.CreateNew()
        elif response.upper() == 'D': # Delete Profile
            try:
                res = int(raw_input('Enter ID of Profile to DELETE or 0 to exit -> '))
                if res != 0:
                    prof.DeleteProfile(res)
                elif res == '0':
                    print 'Back To Menu...'
                else:
                    print 'Unrecognized command. Returning to menu.'
            except ValueError:
                print 'Not a number...back to menu.'    
        else:
            try:
                if int(response) == 1 or int(response) <= prof.totalcount:
                    for x in prof.GetData(int(response)):
                        if x[4] == 1:
                            print 'Calibration Required'
                            exer.Calibrate(x[0])
                        else:
                            print 'Do Exercises'
                            exer.Go(x[0])
                else:
                    print 'Invalid ID. Try again.'
            except:
                print 'Unrecognized command. Try again.'
        raw_input('Press a key to continue ->')
menu()

#set up variables
    #Groups

#analyse profile

    #get last record from profile

    #when were the exercises last performed
        # > 7 days ago - recalibrate
        # < 8 days ago - get current level

#get current level

    #has level been done the right amount of times for this age group
    #has level been done well within the 11 minutes time frame (OK)
        #select the correct level based on the above

#calibrate profile
    #NEW
        #from age and current level of fitness choose initial chart
    #RE-CALIBRATE
        #using last level and days since last performed - choose chart
    #do 2 mins of BX1 - enter no. of repetitions
    #do 1 min of BX2,3,& 4 - enter no. of repetitions
    #do 6 mins of BX5 - enter no. of steps
        #Calculate level for each BX, calculate mean for all - select level

#run exercises

    #Using GetLevel
        #show BX1 and no. of reps required
            #start 2 min timer
            #button clicked at end of reps
            #store time
                #pass -/+ time over to next exercise
            #using 1 min timer do above 3 times
            #using 6 min timer do above 1 time
       
#check level
    #if total time > 11 mins consider going down a level - DOWN
    #if total time < 11 mins
        #if one exercise > required time - STAY
        #if all exercises <= req. time - OK

#timer
    #run timer for selected period
    #stop on button
        
#save profile

#analyse data for user



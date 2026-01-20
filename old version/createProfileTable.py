# -*- coding: utf-8 -*-
import apsw
# Opening/creating database(s)
connection = apsw.Connection("profiles.db3")
cursor = connection.cursor()

# SQL to create Profiles table
sql = 'CREATE TABLE Profiles (id INTEGER PRIMARY KEY, name TEXT, dob DATE, level INTEGER, calibrate INTEGER)'
cursor.execute(sql)


### SQL to create exercise tables
connection = apsw.Connection("exercises.db3")
cursor = connection.cursor()

##sql = 'CREATE TABLE ExerciseTimes (id INTEGER PRIMARY KEY, chart INTEGER, level INTEGER, ex1 INTEGER, ex2 INTEGER, ex3 INTEGER, ex4 INTEGER, ex5 INTEGER)'
##cursor.execute(sql)
##sql = 'CREATE TABLE Instructions (id INTEGER PRIMARY KEY, chart INTEGER, exercise INTEGER, instructions TEXT, image TEXT)'
##cursor.execute(sql)
##sql = 'CREATE TABLE Groups (id INTEGER PRIMARY KEY, age INTEGER, style TEXT, chartId INTEGER)'
##cursor.execute(sql)

# SQL to Insert Recipe
#sql = 'INSERT INTO Recipes (name, servings, source) VALUES ("Spanish Rice", 4, "Greg Walters")'
#cursor.execute(sql)

#Code for entering each exercise

##for chart in range (1,7):
##    for level in range (1,13):
##        loop = True
##        while loop == True:
##            ex1 = raw_input('Chart %d - Level %d : Exercise 1 -> ' % (chart,level))
##            ex2 = raw_input('Chart %d - Level %d : Exercise 2 -> ' % (chart,level))
##            ex3 = raw_input('Chart %d - Level %d : Exercise 3 -> ' % (chart,level))
##            ex4 = raw_input('Chart %d - Level %d : Exercise 4 -> ' % (chart,level))
##            ex5 = raw_input('Chart %d - Level %d : Exercise 5 -> ' % (chart,level))
##
##            response = raw_input('%s | %s | %s | %s | %s -> Is this ok? (y/N) ' % (ex1, ex2, ex3, ex4, ex5))
##            if response.upper() == 'Y':
##                sql = 'INSERT INTO ExerciseTimes (chart, level, ex1, ex2, ex3, ex4, ex5) VALUES ( %d, %d, %d, %d, %d, %d, %d)' % (int(chart), int(level), int(ex1), int(ex2), int(ex3), int(ex4), int(ex5))
##                cursor.execute(sql)
##                print 'Data entered'
##                loop = False
##            else:
##                print 'Re-enter Data'

#Code for entering Instructions

##for chart in range (2,7):
##    for exercise in range (1,6):
##        loop = True
##        while loop == True:
##            instructions = raw_input('Chart %d - Exercise %d -> ' % (chart,exercise))
##            response = raw_input('%s -> \n\nIs this ok? (y/N) ' % instructions) 
##            if response.upper() == 'Y':
##                sql = 'INSERT INTO Instructions (chart, exercise, instructions) VALUES ( %d, %d, "%s")' % (int(chart), int(exercise), instructions)
##                cursor.execute(sql)
##                print 'Data entered'
##                loop = False
##            else:
##                print 'Re-enter Data'

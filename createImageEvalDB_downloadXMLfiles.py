UsageInfo = """
createImageEvalDB_downloadXMLs.py

This program downloads Image Eval XML information from XNAT for every image evaluation,
makes a folder in the current directory called "XML_files", and saves the XML files there.
It parses through all of the downloaded Image Eval XML files and builds an SQLite database
for the image evaluations.
Then creates two PDF files: (a) boxplots for each site that graph the overall image
evaluation scores by the image scan type [ImageEvalBoxplots_perScanType_perSite.pdf]
and (b) a boxplot graphing the overall image evaluation scores by image scan type
[ImageEvalBoxplot_perScanType.pdf].  The ImageEval database is printed to a CSV file
called "ImageEval_database.csv". 

written by Jessica Forbes
"""

from xml.etree import ElementTree as et
import csv
import string
import sys
print sys.path
import sqlite3 as lite
import urllib
import os,argparse,ConfigParser,getpass,subprocess,tempfile,shutil,re
import glob,datetime,stat, getopt
from time import localtime
from pylab import *
from matplotlib.backends.backend_pdf import PdfPages

class ParseXMLFilesAndFillDB():
    
    def __init__(self):
        self.dbFileName = 'ImageEvals.db'
        self.baseXMLpath = ''
        
    def Main(self):
        start_time = datetime.datetime.now()
        
        expList = self.GetExperimentsList()
        self.CreateDataBase()
        self.SetBaseXMLpath()
        self.GetImageEvalXMLsFromXNAT(expList)
        self.FillDBFromXMLs()
        self.PrintDBtoCSVfile()
        
        PerSitePlotObject = MakeBoxPlotPerSite(self.dbFileName)
        PerSitePlotObject.Main()
        PerSitePlotObject = None
        
        PlotObject = MakeBoxPlotForAllEvals(self.dbFileName)
        PlotObject.Main()
        
        print "-"*50
        print "The program took "
        print datetime.datetime.now() - start_time
        
    def GetExperimentsList(self):
        """
        A secure connection to XNAT is created using "urllib".  Then the
        "phd:imagereviewdata/id","phd:imagereviewdata/label","xnat:subjectdata/id",
        "project", and "URI" are retrieved for each image that has been evaluated.
        This information is saved to a temporary file called "experiments_tmp.csv".
        
        Here is an example of the first 5 lines of "experiments_tmp.csv":
        
        "phd:imagereviewdata/id","phd:imagereviewdata/label","xnat:subjectdata/id","project","URI"
        "PREDICTHD_E11437","11349_3_IR","PREDICTHD_S01033","PHD_177","/data/experiments/PREDICTHD_E11437"
        "PREDICTHD_E11519","10026_2_IR","PREDICTHD_S00332","PHD_024","/data/experiments/PREDICTHD_E11519"
        "PREDICTHD_E11520","10026_3_IR","PREDICTHD_S00332","PHD_024","/data/experiments/PREDICTHD_E11520"        
        "PREDICTHD_E11521","10158_2_IR","PREDICTHD_S00202","PHD_041","/data/experiments/PREDICTHD_E11521"
    
        """
        RESTurl = "https://www.predict-hd.net/xnat/REST/experiments?xsiType=phd:imageReviewData&format=csv&columns=project,phd:imageReviewData/label,xnat:subjectData/ID"
        Output = "experiments_tmp.csv"            # names the temporary csv file to hold info from XNAT
        urllib.urlretrieve(RESTurl, Output)       # retrieves info from XNAT and saves it in the temporary csv file
        Handle = open(Output)                     # opens the tmp csv file
        ExpString = Handle.read()                 # reads the csv file and saves to a string
        Handle.close()                            # closes the connection to the csv file
        os.remove(Output)                         # removes tmp csv file
        expList = ExpString.strip().replace("\"","").split('\n')  # removes quotation marks and splits the string into a new list item at each '\n'
        return expList[1:]                        # removes the header line from the returned list
          
    def CreateDataBase(self):
        """
        This creates the ImageEval SQLite database that will contain all of
        the information parsed from the Image Eval XML files.    
        
        """   
        # makes a string variable containing the column titles and types for the ImageEval SQLite database
        dbColTypes =  'project TEXT, subject TEXT, session TEXT, seriesnumber TEXT, scantype TEXT, overallqaassessment TEXT, normalvariants TEXT, lesions TEXT, snr TEXT, '
        dbColTypes += 'cnr TEXT, fullbraincoverage TEXT, misalignment TEXT, swapwraparound TEXT, ghostingmotion TEXT, inhomogeneity TEXT, susceptibilitymetal TEXT, '            
        dbColTypes += 'flowartifact TEXT, truncationartifact TEXT, evaluator TEXT, imagefile TEXT, freeformnotes TEXT, evaluationcompleted TEXT, date TEXT, '
        dbColTypes += 'time TEXT, xnatSubjectID, xnatImageReviewLabel TEXT, xnatImageReviewID TEXT, xnatSessionID TEXT'
    
        if os.path.exists(self.dbFileName):
            os.remove(self.dbFileName)
        if os.path.exists(self.dbFileName):
            print("Using cached db")
        else:
            con = lite.connect(self.dbFileName)
            dbCur = con.cursor()
            dbCur.execute("CREATE TABLE ImageEval({0});".format(dbColTypes))
            dbCur.close()
        
    def SetBaseXMLpath(self):
        CurrentDir = os.getcwd()
        self.baseXMLpath = os.path.join(CurrentDir, "XML_files")
        if not os.path.exists(self.baseXMLpath):
            os.makedirs(self.baseXMLpath)        
      
    def GetImageEvalXMLsFromXNAT(self, expList):
        for line in expList:
            ScanInfo = line.strip().split(',')    # splits the string into list items at a comma
            ID = ScanInfo[0]                      # assigns the ID: "phd:imagereviewdata/id"
            Label = ScanInfo[1]                   # assigns the Label: "phd:imagereviewdata/label"
            xnatSubjectID = ScanInfo[2]           # assigns the xnatSubjectID: "xnat:subjectdata/id"
            Project = ScanInfo[3]                 # assigns the project: "project"
            URI = ScanInfo[4]                     # assigns the URI: "URI"
            xnatPath = "https://www.predict-hd.net/xnat{0}?format=xml".format(URI)  # the URL to the XML info on XNAT
            xmlFileName = "{0}-{1}-{2}-{3}.xml".format(Project, xnatSubjectID, ID, Label)  # the file name for the new XML file
            xmlPath = os.path.join(self.baseXMLpath, xmlFileName)     # makes the path to the XML file
            urllib.urlretrieve(xnatPath, xmlPath)                     # retieves the XML info and saves it in a new XML file
            #print "ImageEval xml file saved for {0}".format(xmlFileName)
            #print "-"*50
               
    def FillDBFromXMLs(self):
        all_files=os.listdir(self.baseXMLpath)
        con = lite.connect(self.dbFileName)
        dbCur = con.cursor()
        for f in all_files:
            fileName, fileExtension = os.path.splitext(f)
            #if fileName.find("FMRI_HD") == -1:
            #    continue
            if fileExtension == ".xml":
                print "-"*20
                print f
                Path = os.path.join(self.baseXMLpath, f)
                ff=open(Path)
                xmlString=ff.read()
                ff.close()
                myResult=None
                myResult=ParseToFields(xmlString)
                
                (subject, scanType) = self.FindSessionAndScanType(myResult._fieldDict['imagefile'])    # finds the scan type from the image file name
                myResult._fieldDict['subject'] = subject
                myResult._fieldDict['scantype'] = scanType
                myResult._fieldDict['date'] = myResult._date
                myResult._fieldDict['time'] = myResult._time
                myResult._fieldDict['project'] = myResult._project
                myResult._fieldDict['xnatImageReviewLabel'] = myResult._label
                myResult._fieldDict['xnatImageReviewID'] = myResult._imageReviewID
                myResult._fieldDict['session'] = myResult._session_LABEL
                myResult._fieldDict['seriesnumber'] = myResult._series_number
    
                xmlFilematch=re.compile('([^-]*)-([^-]*)-([^-]*)-([^-]*).xml.*')
                match=xmlFilematch.match(f)
                if match:
                    myResult._fieldDict['xnatSubjectID']=match.group(2)
                else:
                    print("ERROR: XML filename pattern match failed")
                #print myResult._project
                #print myResult._label
                #print myResult._subject
                #print myResult._session_ID
                #print myResult._session_LABEL
                #print myResult._series_number
                #print myResult._date
                #print myResult._time
                #print myResult._fieldDict
                SQLiteCommand = self.GetSQLiteCommand(myResult._fieldDict)
                myResult = None
                dbCur.execute(SQLiteCommand)
                SQLiteCommand = None
                con.commit()        # commits the SQLite command
                #for scn in myResult._sql_col_names:
                #    unique_sql_col_names[scn]=1
                
        dbCur.close()
                    
    def FindSessionAndScanType(self, imageDir):
        """
        This finds the subject and scan type from the image file name listed in the Image Eval XML file.
        """
        
        imageDirSplit = imageDir.strip().split('/')               # splits the string at each forward slash
        imageFile = imageDirSplit[-1]                             # grabs the image file name
        imageFilePat = re.compile('([^_]*)_[^_]*_([^_]*)_[^-]*')    # sets the pattern for the image file name
        # matches the pattern to the characters in the image file name in order to get the subject and scan type from the file name
        imageFileGroup = imageFilePat.match(imageFile)             
        if imageFileGroup != None and len(imageFileGroup.groups()) == 2:
            subject = imageFileGroup.group(1)                     # sets the subject num to the first group found in the match
            scanType = imageFileGroup.group(2)                    # sets the scanType to the second group found in the match
            return subject, scanType
        else:
            print("ERROR: Invalid number of groups. {0}".format(imageFile))
            return "NOT_FOUND", "NOT_FOUND"
             
    def GetSQLiteCommand(self, EvalDict):
        """
        Cycles through the parsed information gathered for each Image Evaluation XML file.
        Then creates the SQLite command to add info to a new ImageEval database row.        
        """
        ColNames = EvalDict.keys()
        colNamesString = ""
        row =  ""
        for col in ColNames:
            colNamesString += col + ", "                     # adding the column name and a comma to the colNamesString
            evalInfo = EvalDict[col]                         # gets the evaluation info for this subject and session number
            evalInfo = evalInfo.replace("'", "''")           # replaces single apostrophes with double apostrophes for use in SQLite
            row += "'" + evalInfo + "', "                    # adds the eval info to the row string
        trimmedColNameString = colNamesString[:-2]           # trims the excess comma and space from the end of the string
        trimmedRow = row[:-2]                                # trims the excess comma and space from the end of the string
        # creates an SQLite command that adds the data from each Image Eval file to the ImageEval database row by row 
        SQLiteCommand = "INSERT INTO ImageEval (" + trimmedColNameString + ") VALUES (" + trimmedRow + ");"
        return  SQLiteCommand
 
    def PrintDBtoCSVfile(self):
        """
        Prints all of the information in the ImageEval database to a csv file called "ImageEval_database.csv"
        saved in the current working directory.
        """        
        con = lite.connect(self.dbFileName)
        dbCur = con.cursor()
        dbCur.execute("SELECT * FROM ImageEval ORDER BY project, subject, session, seriesnumber, scantype;")
        DBinfo = dbCur.fetchall()
        col_name_list = [tuple[0] for tuple in dbCur.description]
        dbCur.close()
        Handle = csv.writer(open('ImageEval_database.csv', 'wb'),  quoting=csv.QUOTE_ALL)
        Handle.writerow(col_name_list)
        for row in DBinfo:
            Handle.writerow(row)                
   
class MakeBoxPlotPerSite():
    
    def __init__(self, dbFileName):
        self.dbFileName = dbFileName
        self.AllEvalDict = dict()
        
    def Main(self):
        self.MakeEvalDict()
        self.MakePerSiteWhiskerPlots()   
    
    def MakeEvalDict(self):
        """
        Opens a connection to the database containing information parsed from Image Eval XML files.
        Makes a dictionary called 'evalDict' where the KEY is the distinct scan types found in
        the database and the VALUES are a list of the evaluation scores for that scan type.    
        This dictionary is used to obtain average assessment scores by scan type and also create a
        box-and-whisker plot.
        
        """    
        con = lite.connect(self.dbFileName)       # opens a connection to the ImageEval database
        dbCur = con.cursor()                      # opens a cursor to execute SQLite commands
        # uses the cursor to pull the distinct scan types from the ImageEval database
        dbCur.execute("SELECT DISTINCT project FROM ImageEval;")
        # fetches all of the output from the previous execute command and stores each row as an item in a list
        siteList = dbCur.fetchall()
            
        # cycles through the list of scan types to create a dictionary where the Key is the scan type and
        # the Value is the list of evaluation scores for that scan type.
        for site in siteList:
            site = site[0]
            NewSiteObject = AllEvals(site)
            self.AllEvalDict[site] = NewSiteObject
            dbCur.execute("SELECT DISTINCT scantype FROM ImageEval WHERE project = '{0}';".format(site))
            # fetches all of the output from the previous execute command and stores each row as an item in a list
            scanTypeList = dbCur.fetchall()
            for row in scanTypeList:
                scanType = row[0]               # the scan type from the database is stored in a tuple EX: (u'PD-15', )
                # executes an SQLite command that retrieves all the assessment scores for this scan type
                dbCur.execute("SELECT overallqaassessment FROM ImageEval WHERE project = '{0}' AND scantype = '{1}';".format(site, scanType))
                # fetches all of the output from the previous execute command and stores the scores in the evals var
                evals = dbCur.fetchall()
                # MakeEvalList changes the evals from unicode and tuple form i.e. [(u'7',), (u'6',), (u'1',)]
                # to a list of integers necessary for calculations and making a box plot i.e. [7, 6, 1]
                evalList = self.MakeEvalList(evals)   
                self.AllEvalDict[site].AddEvals(scanType, evalList)    
        dbCur.close()    # closes the cursor

    def MakeEvalList(self, evals):
        """
        MakeEvalList changes the evals from unicode and tuple form i.e. [(u'7',), (u'6',), (u'1',)]  
        to a list of integers necessary for calculations and making a box plot i.e. [7, 6, 1]
        """
        evalList = list()
        for x in evals:
            newEval = int(x[0])
            evalList.append(newEval)
        return evalList    
 
    def MakePerSiteWhiskerPlots(self):
        """
        This function makes a box-and-whisker plot showing the evaluation
        scores grouped by the image scan type.  
        
        """
        pp = PdfPages('ImageEvalBoxplots_perScanType_perSite.pdf')
        siteList = self.AllEvalDict.keys()                     # makes a list of all site locations
        siteList = sort(siteList)                              # sorts the list of site locaitons
        scanTypeList = [u'T1-30', u'T2-30', u'T1-15', u'PDT2-15', u'T2-15', u'PD-15']
        for site in siteList:
            SiteObject = self.AllEvalDict[site]                # sets the site object to a variable for easier identification later
            allEvals = list()                                  # makes an empty list which will contain all eval scores
            xLabels = list()                                   # makes an empty list for x labels 
            for scanType in scanTypeList:
                if scanType in SiteObject.Evals.keys():
                    evalScores = SiteObject.Evals[scanType]
                    allEvals.append(evalScores)             # appends the eval scores for this scan type to allEvals
                    # appends the scan type and the number of scans for this type to the xLabel list
                    Count = self.FindEvalsGreaterThan5(evalScores)
                    xLabels.append(scanType + "\n (" + str(Count) + "/" + str(len(evalScores)) + ")")
                else:
                    emptyList = list()
                    allEvals.append(emptyList)             # appends the eval scores for this scan type to allEvals
                    # appends the scan type and the number of scans for this type to the xLabel list
                    xLabels.append(scanType + "\n (0)")
            boxplot(allEvals)
            ylim(-0.1, 10.1)                      # sets the y scale limits between -0.1 and 10.1 since scores are only between 0 and 10
            xticks( arange(1,len(scanTypeList)+1), xLabels, fontsize = 'medium')  # assigns the x labels and fontsize
            yticks(fontsize = 'large')            # assigns y ticks fontsize to large
            xlabel("\n \n Image Scan Type (Ratio of Scores Greater Than 5 to Total Scores)", fontsize = 'large')
            ylabel("Evalution Scores \n", fontsize = 'large')
            title('Evaluation Scores for Site {0} Grouped by Image Scan Type \n \n'.format(site), fontsize = 'large')
            subplots_adjust(bottom = 0.2, top = 0.86, right = .88, left = 0.15)
            subplots_adjust()
            pp.savefig()
            hold(False)          
        pp.close()
        
    def FindEvalsGreaterThan5(self, evalScores):
        Count = 0
        for val in evalScores:
            if val > 5:
                Count += 1
        return Count
        
    def CalculateProportions(self, allEvals):
        PropList = list()
        evalSum = 0
        for x in allEvals:
            evalSum += float(len(x))
        for val in allEvals:
            prop = len(val)/evalSum
            PropList.append(prop)
        return PropList
   
class AllEvals():
    def __init__(self, Site):
        self.Site = Site
        self.Evals = dict()     # dictionary of evaluation scores:  key = image scan type, value = evaluation score

    def AddEvals(self, scanType, evalList):
        self.Evals[scanType] = evalList
           
class ParseToFields():
    def __init__(self,xmlString):
        self._project       = ""  # The project for this XML
        self._label         = ""  # the main label for this subject, in the form of "{sessionID}_{scanid}_IR
        self._imageReviewID = ""
        self._session       = ""
        self._subject_ID    = ""
        self._session_ID    = ""
        self._session_LABEL = ""
        self._series_number = ""
        self._date          = ""
        self._time          = ""
        self._fieldDict     = dict({'susceptibilitymetal': 'NA',
                              'scantype': 'NA',
                              'flowartifact': 'NA',
                              'freeformnotes': ' ',
                              'subject': 'NA',
                              'session': 'NA',
                              'seriesnumber': 'NA',
                              'cnr': 'NA',
                              'overallqaassessment': 'NA',
                              'truncationartifact': 'NA',
                              'ghostingmotion': 'NA',
                              'imagefile': 'NA',
                              'lesions': 'NA',
                              'misalignment': 'NA',
                              'snr': 'NA',
                              'date': 'NA',
                              'evaluator': 'NA',
                              'xnatImageReviewLabel': 'NA',
                              'xnatSessionID': 'NA',
                              'fullbraincoverage': 'NA',
                              'normalvariants': 'NA',
                              'evaluationcompleted': 'NA',
                              'project': 'NA',
                              'swapwraparound': 'NA',
                              'inhomogeneity': 'NA',
                              'time': 'NA'}) ## Need to do a copy of dictionary.
        self._sql_col_names  = list()
        self._string=xmlString
        myelem=et.fromstring(self._string)
        self._project=myelem.attrib['project']
        self._label  =myelem.attrib['label']
        self._imageReviewID = myelem.attrib['ID']
        self._session_LABEL=self._label[0:5] ## the first 5 digits are always the session label
        for child in myelem.getiterator():
            if child.tag == '{http://nrg.wustl.edu/phd}field':
                myatts=dict(child.items())
                self._sql_col_names.append(self.makeSQLColName(myatts['name']))
                if 'value' in myatts.keys(): 
                    self._fieldDict[self.makeSQLColName(myatts['name'])] = myatts['value']
                # some XML files have no value for "free form notes". This assigns an empty string.
                elif 'value' not in myatts.keys() and myatts['name'] == "Free Form Notes":
                    self._fieldDict[self.makeSQLColName(myatts['name'])] = " "
                    print "ERROR: No value for the \"Free Form Notes\" field in the XML file for {0}".format(self._imageReviewID)
                pass
            elif child.tag  == '{http://nrg.wustl.edu/xnat}date':
                self._date = child.text
                pass
            elif child.tag  == '{http://nrg.wustl.edu/xnat}time':
                self._time = child.text
                pass
            elif child.tag  == '{http://nrg.wustl.edu/phd}series_number':
                self._series_number = child.text
                pass
            elif child.tag  == '{http://nrg.wustl.edu/xnat}imageSession_ID':
                self._session_ID = child.text
                pass
            
    def makeSQLColName(self, val):
        val=val.replace(' ','').replace('/','').lower()
        return val
 
class MakeBoxPlotForAllEvals():

    def __init__(self, dbFileName):
        self.dbFileName = dbFileName
        self.evalDict = dict()       # makes an empty dictionary called evalDict
        
    def Main(self):
        self.MakeEvalDict()
        self.MakeWhiskerPlot()
     
    def MakeEvalDict(self):
        """
        Opens a connection to the database containing information parsed from Image Eval XML files.
        Makes a dictionary called 'evalDict' where the KEY is the distinct scan types found in
        the database and the VALUES are a list of the evaluation scores for that scan type.    
        This dictionary is used to obtain average assessment scores by scan type and also create a
        box-and-whisker plot.        
        """    
        
        con = lite.connect(self.dbFileName)       # opens a connection to the ImageEval database
        dbCur = con.cursor()                      # opens a cursor to execute SQLite commands
        # uses the cursor to pull the distinct scan types from the ImageEval database
        dbCur.execute("SELECT DISTINCT scantype FROM ImageEval;")
        # fetches all of the output from the previous execute command and stores each row as an item in a list
        scanTypeList = dbCur.fetchall()
        
        # cycles through the list of scan types to create a dictionary where the Key is the scan type and
        # the Value is the list of evaluation scores for that scan type.
        for row in scanTypeList:
            scanType = row[0]                   # the scan type from the database is stored in a tuple EX: (u'PD-15', )
            # executes an SQLite command that retrieves all the assessment scores for this scan type
            dbCur.execute("SELECT overallqaassessment FROM ImageEval WHERE scantype = '{0}';".format(scanType))
            # fetches all of the output from the previous execute command and stores the scores in the evals var
            evals = dbCur.fetchall()
            # MakeEvalList changes the evals from unicode and tuple form i.e. [(u'7',), (u'6',), (u'1',)]
            # to a list of integers necessary for calculations and making a box plot i.e. [7, 6, 1]
            evalList = self.MakeEvalList(evals)   
            Key = scanType                      # sets the Key to scanType
            self.evalDict[Key] = evalList       # adds the evaluation score list as a Value to the evalDict dictionary
        
        dbCur.close()    # closes the cursor
       
    def MakeEvalList(self, evals):
        """
        MakeEvalList changes the evals from unicode and tuple form i.e. [(u'7',), (u'6',), (u'1',)]  
        to a list of integers necessary for calculations and making a box plot i.e. [7, 6, 1]
        """
        evalList = list()
        for x in evals:
            newEval = int(x[0])
            evalList.append(newEval)
        return evalList
    
    def FindEvalsGreaterThan5(self, evalScores):
        Count = 0
        for val in evalScores:
            if val > 5:
                Count += 1
        return Count
    
    def MakeWhiskerPlot(self):
        """
        This function makes a box-and-whisker plot showing the evaluation
        scores grouped by the image scan type.          
        """    
        allEvals = list()                     # makes an empty list called Evals
        scanTypeList = [u'T1-30', u'T2-30', u'T1-15', u'PDT2-15', u'T2-15', u'PD-15']
        xLabels = list()                      # makes an empty list for x labels 
        for scanType in scanTypeList:
            evalScores = self.evalDict[scanType]
            allEvals.append(evalScores)       # appends the eval scores for this scan type to allEvals
            Count = self.FindEvalsGreaterThan5(evalScores)
            xLabels.append(scanType + "\n (" + str(Count) + "/" + str(len(evalScores)) + ")")
        boxplot(allEvals)                     # makes a box-and-whisker plot of scores grouped by scan type
        ylim( -0.1, 10.1)                     # sets the y scale limits between -0.1 and 10.1 since scores are only between 0 and 10
        xticks( arange(1,len(scanTypeList)+1), xLabels, fontsize = 'small')  # assigns the x labels and fontsize
        yticks(fontsize = 'large')            # assigns y ticks fontsize to large
        xlabel("\n \n Image Scan Type (Ratio of Scores Greater Than 5 to Total Scores)", fontsize = 'large')
        ylabel("Evalution Scores \n", fontsize = 'large')
        title('Evaluation Scores Grouped by Image Scan Type \n \n', fontsize = 'x-large')
        subplots_adjust(bottom = 0.2, top = 0.86, right = .88, left = 0.15)
        savefig("ImageEvalBoxplot_perScanType.pdf")

if __name__ == "__main__":
   
    Object = ParseXMLFilesAndFillDB()
    Object.Main()
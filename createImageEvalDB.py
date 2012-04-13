UsageInfo = """
createImageEvalDB.py

This program pulls Image Eval XML information from XNAT for every image
evaluation. It parses this information and builds an SQLite database for the
image evaluations. Then creates two PDF files: (a) boxplots for each site that
graph the overall image evaluation scores by the image scan type
[ImageEvalBoxplots_perScanType_perSite.pdf] and (b) a boxplot graphing the
overall image evaluation scores by image scan type
[ImageEvalBoxplot_perScanType.pdf].  The ImageEval database is printed to a
CSV file called "ImageEval_database.csv". 
 
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
from matplotlib.backends.backend_pdf import PdfPages as pdfpages

class ParseXMLFilesAndFillDB():
    
    def __init__(self):
        self.dbFileName = 'ImageEvals.db'
        
    def main(self):
        expList = self.getExperimentsList()
        self.createDataBase()        
        self.fillDBFromXMLs(expList)
        self.printDBtoCSVfile()
        self.printInfoToCSVfile()
        
    def getExperimentsList(self):
        """
        Create a secure connection to XNAT using "urllib".  Then the
        "phd:imagereviewdata/id", "phd:imagereviewdata/label",
        "xnat:subjectdata/id", "project", and "URI" are retrieved for each
        image that has been evaluated. This information is saved to a temporary
        file called "experiments_tmp.csv".
        
        Here is an example of the first 5 lines of "experiments_tmp.csv":
        
        "phd:imagereviewdata/id","phd:imagereviewdata/label","xnat:subjectdata/id","project","URI"
        "PREDICTHD_E11437","11349_3_IR","PREDICTHD_S01033","PHD_177","/data/experiments/PREDICTHD_E11437"
        "PREDICTHD_E11519","10026_2_IR","PREDICTHD_S00332","PHD_024","/data/experiments/PREDICTHD_E11519"
        "PREDICTHD_E11520","10026_3_IR","PREDICTHD_S00332","PHD_024","/data/experiments/PREDICTHD_E11520"        
        "PREDICTHD_E11521","10158_2_IR","PREDICTHD_S00202","PHD_041","/data/experiments/PREDICTHD_E11521"
    
        """
        RESTurl = "https://www.predict-hd.net/xnat/REST/experiments?xsiType="
        RESTurl += "phd:imageReviewData&format=csv&columns=project,phd:image"
        RESTurl += "ReviewData/label,xnat:subjectData/ID"
        Output = "experiments_tmp.csv"
        urllib.urlretrieve(RESTurl, Output)
        Handle = open(Output)
        ExpString = Handle.read()
        Handle.close()
        os.remove(Output)
        expList = ExpString.strip().replace("\"","").split('\n')
        return expList[1:] ## header line not needed in the returned list
          
    def createDataBase(self):
        """
        Create the ImageEval SQLite database that will contain all of
        the information parsed from the Image Eval XML files.            
        """   
        ## column titles and types for the ImageEval SQLite database
        dbColTypes =  "project TEXT, subject INTEGER, session INTEGER, seriesnumber INTEGER, scantype TEXT, "
        dbColTypes += "overallqaassessment INTEGER, normalvariants TEXT, lesions TEXT, snr TEXT, cnr "
        dbColTypes += "TEXT, fullbraincoverage TEXT, misalignment TEXT, swapwraparound TEXT, "
        dbColTypes += "ghostingmotion TEXT, inhomogeneity TEXT, susceptibilitymetal TEXT, "
        dbColTypes += "flowartifact TEXT, truncationartifact TEXT, evaluator TEXT, imagefile "
        dbColTypes += "TEXT, freeformnotes TEXT, evaluationcompleted TEXT, date TEXT, time TEXT, "
        dbColTypes += "xnatSubjectID TEXT, xnatImageReviewLabel TEXT, xnatImageReviewID TEXT, "
        dbColTypes += "xnatSessionID TEXT"
    
        if os.path.exists(self.dbFileName):
            os.remove(self.dbFileName)
        if os.path.exists(self.dbFileName):
            print("Using cached db")
        else:
            con = lite.connect(self.dbFileName)
            dbCur = con.cursor()
            dbCur.execute("CREATE TABLE ImageEval({0});".format(dbColTypes))
            dbCur.close()
            
    def fillDBFromXMLs(self, expList):
        con = lite.connect(self.dbFileName)
        dbCur = con.cursor()
        
        for line in expList:
            (xnatSubjectID, URI) = self._getScanInfo(line)
            xmlString = self.getXMLstring(URI)            
            myResult=ParseToFields(xmlString)
            xmlString = None
            # find the scan type from the image file name
            (subject, scanType) = self._findSessionAndScanType(myResult._fieldDict['imagefile'])
            myResult._fieldDict['subject'] = subject
            myResult._fieldDict['scantype'] = scanType
            myResult._fieldDict['xnatSubjectID']= xnatSubjectID    
            myResult._fieldDict['date'] = myResult._date
            myResult._fieldDict['time'] = myResult._time
            myResult._fieldDict['project'] = myResult._project
            myResult._fieldDict['xnatImageReviewLabel'] = myResult._label
            myResult._fieldDict['xnatImageReviewID'] = myResult._imageReviewID
            myResult._fieldDict['session'] = myResult._session_LABEL
            myResult._fieldDict['seriesnumber'] = myResult._series_number
    
            SQLiteCommand = self._getSQLiteCommand(myResult._fieldDict)
            myResult = None
            dbCur.execute(SQLiteCommand)
            SQLiteCommand = None
            con.commit()
                  
        dbCur.close()
                    
    def _getScanInfo(self, line):
        """ Returns the XNAT Subject ID and the URI for an Image Eval. """
        scan_info = line.strip().split(',')
        xnat_subject_ID = scan_info[2]
        URI = scan_info[4]
        return xnat_subject_ID, URI
                
    def getXMLstring(self, URI):
        """
        Copy the Image Eval XML information from XNAT.
        Store it in the string "xmlString"
        """
        path = "https://www.predict-hd.net/xnat{0}?format=xml".format(URI)
        Handle = urllib.urlopen(path)
        xml_string = Handle.read()
        Handle.close()
        #print "Parsing Image Eval XML file from {0}".format(path)
        return xml_string
                
    def _findSessionAndScanType(self, imageDir):
        """
        Find the subject and scan type from the image file name
        listed in the Image Eval XML string.
        """
        _image_dir_split = imageDir.strip().split('/') 
        _image_file = _image_dir_split[-1]
        _image_file_pattern = re.compile('([^_]*)_[^_]*_([^_]*)_[^-]*')
        _image_file_group = _image_file_pattern.match(_image_file)             
        if _image_file_group is not None and len(_image_file_group.groups()) == 2:
            _subject = _image_file_group.group(1)
            _scanType = _image_file_group.group(2)
            return _subject, _scanType
        else:
            print("ERROR: Invalid number of groups. {0}".format(_image_file))
            return "NOT_FOUND", "NOT_FOUND"
             
    def _getSQLiteCommand(self, EvalDict):
        """
        Cycle through the parsed information gathered for each Image Evaluation
        XML file. Create the SQLite command to add info to a new ImageEval
        database row.        
        """
        _col_names = EvalDict.keys()
        _col_names_str = ""
        _row =  ""
        for _col in _col_names:
            _col_names_str += "{0}, ".format(_col)
            _eval_info = EvalDict[_col]
            _eval_info = _eval_info.replace("'", "''")
            _row += "'{0}', ".format(_eval_info)
        _col_names_str = _col_names_str[:-2] ## trim the excess comma and space from the end of the string
        _row = _row[:-2]                     ## trim the excess comma and space from the end of the string
        # create an SQLite command that adds data from each Image Eval file to the ImageEval database row by row 
        _SQLite_command = "INSERT INTO ImageEval ({0}) VALUES ({1});".format(_col_names_str, _row)
        return  _SQLite_command
 
    def printDBtoCSVfile(self):
        """
        Print all of the information in the ImageEval database to a csv file
        called "ImageEval_database.csv" saved in the current working directory.
        """
        con = lite.connect(self.dbFileName)
        dbCur = con.cursor()
        SQLiteCommand = "SELECT * FROM ImageEval ORDER BY project, subject, session, seriesnumber, scantype;"
        dbCur.execute(SQLiteCommand)
        DBinfo = dbCur.fetchall()
        col_name_list = [tuple[0] for tuple in dbCur.description]
        dbCur.close()
        Handle = csv.writer(open('ImageEval_database.csv', 'wb'),
                            quoting=csv.QUOTE_ALL)
        Handle.writerow(col_name_list)
        for row in DBinfo:
            Handle.writerow(row)                
         
    def printInfoToCSVfile(self):
        """
        
        """                
        Handle = csv.writer(open('proj_subj_session_imagefiles.csv', 'wb'),
                            quoting=csv.QUOTE_ALL)
        col_name_list = ["project", "subject", "session", "imagefiles"]
        Handle.writerow(col_name_list)
        tmp_session = None
        line = None
        imagefile_info = self.getImageFileInfoFromDB()
        for row in imagefile_info:
            project = str(row[0])
            subject = str(row[1])
            session = str(row[2])
            scan_type = str(row[4])
            imagefile = str(row[5])
            if tmp_session != session:
                eval_dict = dict()
                eval_dict[scan_type] = [imagefile]
                if line is not None:
                    Handle.writerow(line) 
            else:
                if scan_type in eval_dict.keys():
                    eval_dict[scan_type].append(imagefile)
                else:
                    eval_dict[scan_type] = [imagefile]
            tmp_session = session
            sorted_eval_dict = sort(eval_dict)
            line = (project, subject, session, sorted_eval_dict)
         
    def getImageFileInfoFromDB(self):
        con = lite.connect(self.dbFileName)
        dbCur = con.cursor()
        SQLiteCommand = "SELECT project, subject, session, overallqaassessment, scantype, imagefile "
        SQLiteCommand += "FROM ImageEval WHERE overallqaassessment > 5 "
        SQLiteCommand += "ORDER BY project, subject, session, scantype, overallqaassessment DESC;"
        dbCur.execute(SQLiteCommand)
        DBinfo = dbCur.fetchall()
        dbCur.close()
        return DBinfo
         
class ParseToFields():
    def __init__(self,xmlString):
        self._project       = ""  # The project for this XML main label for this subject,
                                  # in the form of "{sessionID}_{scanid}_IR
        self._label         = ""
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
                              'time': 'NA'})
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
                ## Assign an empty string if there is no value for "free form notes".
                elif 'value' not in myatts.keys() and myatts['name'] == "Free Form Notes":
                    self._fieldDict[self.makeSQLColName(myatts['name'])] = " "
                    print "ERROR: No value for \"Free Form Notes\" field in ImageEval for {0}".format(self._imageReviewID)
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
        val = val.replace(' ','').replace('/','').lower()
        return val

class MakeBoxplots():
    
    def __init__(self):
        self.dbFileName = 'ImageEvals.db'
        
    def main(self):
        self.makeAllSiteBoxPlotNEW()
        self.makePerSiteBoxPlotNEW()

    def getEvalScores(self, SQLite_query):
        """
        MakeEvalList changes the evals from unicode and tuple form i.e. [(u'7',), (u'6',), (u'1',)]  
        to a list of integers necessary for calculations and making a box plot i.e. [7, 6, 1]
        """
        query_results = self._querySQLiteDB(SQLite_query)
        eval_list = list()
        for row in query_results:
            new_eval = float(row[0])
            eval_list.append(new_eval)
        return eval_list      
        
    def _findEvalsGreaterThan5(self, evalScores):
        count = 0
        for val in evalScores:
            if val > 5:
                count += 1
        return count
    
    def _querySQLiteDB(self, SQLite_query):
        con = lite.connect(self.dbFileName)
        dbCur = con.cursor()
        dbCur.execute(SQLite_query)
        query_results = dbCur.fetchall()
        dbCur.close()
        return query_results
    
    def getListFromDB(self, SQLite_query):
        query_results = self._querySQLiteDB(SQLite_query)
        List = list()
        # the scan type from the database is stored in a tuple EX: (u'PD-15', )
        for row in query_results:
            list_item = row[0]
            List.append(list_item)
        return List

    def getEvalScoresAndXticks(self, site = None):
        scanTypeList = [u'T1-30', u'T2-30', u'T1-15', u'PDT2-15', u'T2-15', u'PD-15']
        all_evals = list()
        x_labels = list()        
        query_1 = self.getQuery1(site)
        DB_scan_types = self.getListFromDB(query_1)    
        
        for scan_type in scanTypeList:
            if scan_type in DB_scan_types:
                query_2 = self.getQuery2(site, scan_type)
                eval_scores = self.getEvalScores(query_2)   
                all_evals.append(eval_scores)
                count = self._findEvalsGreaterThan5(eval_scores)
                x_labels.append(scan_type + "\n (" + str(count) + "/" + str(len(eval_scores)) + ")")
            else:
                all_evals.append(list())
                x_labels.append(scan_type + "\n (0)")
        return all_evals, x_labels, scanTypeList
    
    def makePerSiteBoxPlotNEW(self):
        """
        This function makes a box-and-whisker plot showing the evaluation
        scores grouped by the image scan type.  
        """
        #pp = pdfpages('test.pdf')
        pp = pdfpages('ImageEvalBoxplots_perScanType_perSite.pdf')
        site_list = self.getListFromDB("SELECT DISTINCT project FROM ImageEval;")
        for site in site_list:
            (all_evals, x_labels, scanTypeList) = self.getEvalScoresAndXticks(site)
            boxplot(all_evals)
            ylim(-0.1, 10.1)
            xticks( arange(1, len(scanTypeList)+1), x_labels, fontsize = 'medium')
            yticks(fontsize = 'large')
            xlabel("\n \n Image Scan Type (Ratio of Scores Greater Than 5 to Total Scores)", fontsize = 'large')
            ylabel("Evalution Scores \n", fontsize = 'large')
            title('Evaluation Scores for Site {0} Grouped by Image Scan Type \n \n'.format(site), fontsize = 'large')
            subplots_adjust(bottom = 0.2, top = 0.86, right = .88, left = 0.15)
            pp.savefig()
            hold(False)
        pp.close()
        
    def makeAllSiteBoxPlotNEW(self):
        """
        This function makes a box-and-whisker plot showing the evaluation
        scores grouped by the image scan type.          
        """
        (all_evals, x_labels, scanTypeList) = self.getEvalScoresAndXticks()
        boxplot(all_evals)
        ylim(-0.1, 10.1)
        xticks( arange(1, len(scanTypeList)+1), x_labels, fontsize = 'small')
        yticks(fontsize = 'large')
        xlabel("\n \n Image Scan Type (Ratio of Scores Greater Than 5 to Total Scores)", fontsize = 'large')
        ylabel("Evalution Scores \n", fontsize = 'large')
        title('Evaluation Scores Grouped by Image Scan Type \n \n', fontsize = 'x-large')
        subplots_adjust(bottom = 0.2, top = 0.86, right = .88, left = 0.15)
        #savefig("test_perscantype.pdf")
        savefig("ImageEvalBoxplot_perScanType.pdf")
        hold(False)        
    
    def getQuery1(self, site):
        if site is None:
            query1 = "SELECT DISTINCT scantype FROM ImageEval;"
        else:
            query1 = "SELECT DISTINCT scantype FROM ImageEval WHERE project = '{0}';".format(site)
        return query1
    
    def getQuery2(self, site, scan_type):
        if site is None:
            query2 = "SELECT overallqaassessment FROM ImageEval WHERE scantype = '{0}';".format(scan_type)
        else:
            query2 = "SELECT overallqaassessment FROM ImageEval WHERE project = '{0}' AND scantype = '{1}';".format(site, scan_type)
        return query2

if __name__ == "__main__":
    start_time = datetime.datetime.now()
    Object = ParseXMLFilesAndFillDB()
    Object.main()
    PlotObject = MakeBoxplots()
    PlotObject.main()
    print "-"*50
    print "The program took "
    print datetime.datetime.now() - start_time

MANUSCRIPT
Assignment Feedback in School Choice Mechanisms

FILE EXTENSIONS
Files with the ".py" extension are Python scripts.
For more information about Python, see https://www.python.org/
Files with the ".r" extension are R scripts.
For more information about R, see https://www.r-project.org/
Files withe the ".csv" extension are CSV data.
A comma-separated values (CSV) file is a delimited text file that uses a comma to separate values.

OVERVIEW OF EXPERIMENTAL PROGRAM FILES
SchoolChoiceServer.exe: The server program for hosting the experiment
SchoolChoiceClient.exe: The client program for participating in the experiment
SchoolChoiceInstuctions.pdf: A PDF copy of the experimental instructions.
Files with the ".dll" extension are dynamic linked libraries.
The library files must be placed in the same folder as the ".exe" files.

OVERVIEW OF ANALYSIS FILES
MaxLik.py: Parameter estimation for the adptive model
PathByPeriod.r: Generation of plots illustrating the path of behavior over time within each period
PathPeriodAcross.r: Generation of plots illustrating the mean path of behavior over time across periods
PathPeriodWithin.r: Generation of plots illustrating the mean path of behavior over time within periods
RankSumTest.r: Hypothesis testing for equilibrium, best responding, justified envy, and efficiency
Truth.r: Hypothesis testing for truthful preference revelation

OVERVIEW OF DATA FILES
SchoolChoiceData.csv: The data collected from the experiment in CSV format.
README.txt: A readme file summarizing the data and programs provided in this repository.

VARIABLE NAMES AND DEFINITIONS
session: The experimental session
feedback: The type of feedback provided, real time or discrete
mechanism: The student assignment mechanism
period: The period within the experimental session
subject: The ID of the subject in the experimental session
type: The type of the subject a described in section 3.1
truth: The subject's truthful preference report 
lotto: The lottery number assigned to the subject for breaking ties withing a type
second: The number of seconds currently elaspsed within the period
assignment: The subject's assignment under the currect reports
report: The preference report selected by the subject
pay1: The subject's potential payoff from report 1
pay2: The subject's potential payoff from report 2
pay3: The subject's potential payoff from report 3
pay4: The subject's potential payoff from report 4
pay5: The subject's potential payoff from report 5
pay6: The subject's potential payoff from report 6

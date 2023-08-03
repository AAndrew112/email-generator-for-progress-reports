# email-generator-for-progress-reports

## Overview

The email-generator-for-progress-reports project is designed to automate the task of narrowing down the list of students needed to be contacted by each advisor for progress reports. It simplifies the process by extracting relevant student details and progress reports and generating a list of email addresses, individualized to each co-advisor team.

## Requirements

- **Python Version**: 3.x or above
- **Libraries**: pandas

## Usage

### Step 1: Generate the Members.csv File

- Navigate to the members page on the HQ (company website).
- Select the download icon on the top right to download the `Members.csv` file containing the required student information.

### Step 2: Prepare the progress_report.csv File

- Ensure that you have a CSV file named `progress_report.csv` containing the progress information in the same directory as the script.

### Step 3: Run the Script

- Run the script to generate a comma-separated list of email addresses for students who are partway through the program.

**Note**: Both CSV files (`Members.csv` and `progress_report.csv`) must be in the same directory as the script for it to run correctly.

## Contact

For any questions or concerns please reach out at amanda.andrew112@gmail.com



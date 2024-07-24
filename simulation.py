import numpy as np
import pandas as pd
import xlsxwriter
import datetime
from dateutil.relativedelta import *
import json
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import locale

locale.setlocale( locale.LC_ALL, '' )

# todo:
# look at justin's spreadsheet and add extra house parameters. Validate against his spreadsheet's results

class Account:
    name = ""
    initial_balance = 0.0
    interest = 0

    def deposit(self, amount):
        self.balance += amount

    def withdrawal(self, amount):
        self.balance -= amount

    # json dictionary auto-constructor
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.balance = self.initial_balance
        self.interest = self.interest / 100.0

class Loan:
    name = ""
    initial_balance = 0.0
    interest = 0.0
    asset_name = ""
    asset_initial_value = 0
    asset_value = 0
    asset_appreciation = 0
    start_date = None
    down_payment = None
    contributes_net_worth = False
    started = False

    def deposit(self, amount):
        self.balance -= amount

    def withdrawal(self, amount):
        self.balance += amount    

    def start(self, downPaymentSourceAccounts = None):
        self.started = True
        if(self.down_payment != None and self.down_payment["amount"] != 0):
            # take as much as possible from each account in order until target is reached
            transferBalance = self.down_payment["amount"]
            for account in downPaymentSourceAccounts:
                # take what is needed or drain the account if there isn't enough
                transferAmount = min(account.balance, transferBalance)
                transferBetweenAccounts(account, self, transferAmount)
                transferBalance -= transferAmount
                if(transferBalance == 0):
                    break
            if(transferBalance != 0):
                raise Exception("invalid down payment transfer")

    # json dictionary auto-constructor
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.balance = self.initial_balance
        self.interest = self.interest / 100.0
        self.asset_value = self.asset_initial_value
        self.asset_appreciation = self.asset_appreciation / 100.0
        if "start_date" in kwargs:
            self.start_date = datetime.datetime.strptime(self.start_date, "%m/%Y").date()
            if(self.start_date < datetime.date.today()):
                raise Exception("Loan start_date is in the past. Remove this date if you intended to initialize in a started state.")
            self.started = False # allow simulation to call start
        else:
            if(self.down_payment != None and self.down_payment["amount"] != 0):
                raise Exception("Cannot initialize loan in started state with a down payment. Subtract from initial_balance in simulation parameters if this was intended.")
            self.start()

class RecurringCost:
    name = ""
    amount = 0,
    start_date = None
    end_date = None
    started = False
    ended = False

    # json dictionary auto-constructor
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        
        if("start_date" in kwargs):
            self.start_date = datetime.datetime.strptime(self.start_date, "%m/%Y").date()
            if(self.start_date < datetime.date.today()):
                raise Exception("recurring cost start_date is in the past. Remove this date if you intended to initialize in a started state.")
            # if a start date was provided, do not auto start                
            self.started = False
        else:
            self.started = True
            
        if("end_date" in kwargs):
            self.end_date = datetime.datetime.strptime(self.end_date, "%m/%Y").date()
            if(self.end_date <= datetime.date.today()):
                raise Exception("recurring cost end_date is in the past.")
            
        if("start_date" in kwargs and "end_date" in kwargs):
            if(self.start_date <= self.end_date):
                raise Exception("recurring cost start date must be before end date if both are supplied.")

class ScheduledTransfer:
    source = ""
    destination = ""
    amount = 0.0
    date = None
    description = ""
    complete = False

    # json dictionary auto-constructor
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.date = datetime.datetime.strptime(self.date, "%m/%Y").date()

accounts = dict()
loans = dict()
contributions = dict()
monthlyCosts = list()
scheduledTransfers = list()
compoundFrequency = 12.0 # once per month, 12 times per year

# simulation parameters
monthly_surplus = 0
rent = 0
simulation_length_months = 0
leftover_contribution_account = ""
export_excel = False
export_filename = ""


#simulation variables
df = None
simulationRow = 0
currentDate = datetime.date.today()

def transferBetweenAccounts(source, destination, amount):
    # calling deposit or withdrawal may add or subtract balance depending on if the account is a loan
    source.withdrawal(amount)
    destination.deposit(amount)
    

def simulateMonth(investable_income):
    global currentDate
    global simulationRow
    
    df.at[simulationRow, "date"] = currentDate
    df.at[simulationRow, "surplus"] = investable_income
    
    # how much we have left to spend this month
    availableDeposit = investable_income

    # subtract recurring costs from availableDeposit
    totalMonthlyCosts = 0
    for cost in monthlyCosts:
        if cost.ended == True:
            continue
        if cost.started == False and cost.start_date <= currentDate:
            cost.started = True
        if cost.started == True:
            if cost.end_date != None and cost.end_date <= currentDate:
                cost.ended = True
            else:
                totalMonthlyCosts += cost.amount
                availableDeposit -= cost.amount
    df.at[simulationRow, "monthly_costs"] = totalMonthlyCosts

    # contribute to loans
    for name, loan in loans.items():  
        if loan.started == False:
            if loan.start_date <= currentDate:
                sources = [accounts[name] for name in loan.down_payment["sources"]]
                loan.start(sources)
            else:
                df.at[simulationRow, loan.name] = 0.0
                if(loan.asset_name != "" and loan.contributes_net_worth):
                    df.at[simulationRow, loan.asset_name] = 0.0

        if loan.started == True:
            # compound loans have interested added every amortization period
            interest = loan.balance * (loan.interest / compoundFrequency)
            loan.balance += interest

            # add fixed contribuation amount
            if(loan.name in contributions):
                contribution = contributions[loan.name]

                # handle completion of the loan
                if loan.balance - contribution < 0:
                    contribution = loan.balance

                df.at[simulationRow, (loan.name + "_contribution")] = contribution

                loan.balance -= contribution
                availableDeposit -= contribution
                
            df.at[simulationRow, loan.name] = loan.balance

            if(loan.asset_name != "" and loan.contributes_net_worth):
                # apply asset appreciation/depreciation
                loan.asset_value += loan.asset_value * (loan.asset_appreciation / compoundFrequency)

                df.at[simulationRow, loan.asset_name] = loan.asset_value

    # make fixed contributions to savings accounts
    for name, account in accounts.items():
        interest = account.balance * (account.interest / compoundFrequency)
        account.balance += interest

        if account.name in contributions:
            contribution = contributions[account.name]
            df.at[simulationRow, (account.name + "_contribution")] = contribution

            account.balance += contribution
            availableDeposit -= contribution
        
        df.at[simulationRow, account.name] = account.balance
        

    # contribute remaining funds into selected leftover account 

    if(availableDeposit < 0):
        raise Exception("Invalid configuration: Over contributing to accounts!")
    
    account = accounts[leftover_contribution_account]
    interest = account.balance * (account.interest / compoundFrequency)
    account.balance += interest

    contribution = availableDeposit - rent
    df.at[simulationRow, (leftover_contribution_account + "_contribution")] = contribution 

    account.balance += contribution

    df.at[simulationRow, account.name] = account.balance

    # perform scheduled transfers
    for transfer in scheduledTransfers:
        if transfer.complete == False and transfer.date <= currentDate:
            if transfer.destination == "void":
                # spent money
                accounts[transfer.source].withdrawal(transfer.amount)
                df.at[simulationRow, "spent"] += transfer.amount
            else:
                # transferred 
                transferBetweenAccounts(accounts[transfer.source], accounts[transfer.destination])
            transfer.complete = True

    # calculate net worth
    net = 0
    for account in accounts.values():
        net += account.balance
    for loan in loans.values():
        if loan.started == True:
            net -= loan.balance
            if(loan.contributes_net_worth):
                net += loan.asset_value
    df.at[simulationRow, "net_worth"] = net

    currentDate = currentDate + relativedelta(months=+1)
    simulationRow += 1


def columnName(column):
    if(column > 25):
        raise Exception("Too many columns. Add support for more column letters")
    return chr(column + 65)

with open("params.json") as f:
    data = json.load(f)
    leftover_contribution_account = data["leftover_contribution_account"]
    monthly_surplus = data["monthly_surplus"]
    simulation_length_months = data["simulation_length_months"]
    export_excel = data["export_excel"]
    export_filename = data["export_filename"]

    if "accounts" not in data:
        raise Exception("must supply at least on account")

    accounts = { a["name"] : Account(**a) for a in data["accounts"] }
     
    if any(account.name == leftover_contribution_account for name, account in accounts.items()) == False:
        raise Exception("leftover_contribution_account must be supplied and equal to the name of an account")

    if "loans" in data:
        loans = { l["name"] : Loan(**l) for l in data["loans"] }
    if "monthly_costs" in data:
        monthlyCosts = [ RecurringCost(**c) for c in data["monthly_costs"] ]

    contributions = {c[0] : c[1] for c in data["monthly_contributions"]}
    if(leftover_contribution_account in contributions):
        raise Exception("cannot include leftover_contribution_account in fixed contributions")
    
    scheduledTransfers = [ScheduledTransfer(**s) for s in data["one_time_transfers"]]

simulationStructure = {
    "date": [None] * simulation_length_months,
    "surplus": [None] * simulation_length_months
}
simulationStructure.update({acc.name : [np.nan] * simulation_length_months for name, acc in accounts.items()})
simulationStructure.update({loan.name : 0 * simulation_length_months for name, loan in loans.items()})
usedAssets = {loan.asset_name : 0 * simulation_length_months for name, loan in loans.items() if loan.asset_name != "" and loan.contributes_net_worth}
simulationStructure.update(usedAssets)
simulationStructure.update({"monthly_costs": [np.nan] * simulation_length_months}) 

# these contribution columns are just for the spreadsheet
for name, amount in contributions.items():
    simulationStructure.update({(name + "_contribution"): 0 * simulation_length_months}) 
simulationStructure.update({(leftover_contribution_account + "_contribution"): 0 * simulation_length_months}) 

simulationStructure.update({"spent": 0 * simulation_length_months})

simulationStructure.update({"net_worth": [np.nan] * simulation_length_months})

df = pd.DataFrame(simulationStructure)

# run the simulation
for i in range(simulation_length_months):
    simulateMonth(monthly_surplus)

# print end state
for name, account in accounts.items():
    print(account.name, " ", locale.currency(account.balance, grouping=True))
for name, loan in loans.items():
    if(loan.balance > 0):
        print(loan.name, " ", locale.currency(loan.balance, grouping=True))
print("net_worth ", locale.currency(df.at[simulation_length_months -1, "net_worth"], grouping=True))

    
# export excel file
if export_excel:
    sheetName = "spending_scenario"
    with pd.ExcelWriter(export_filename, engine='xlsxwriter', date_format="MM-YYYY") as writer:
        df.to_excel(writer, sheet_name=sheetName, index = False)

        # format cells as currency
        workbook  = writer.book
        worksheet = writer.sheets[sheetName]
        currency_format = workbook.add_format({'num_format': '$#,##0.00'})
        percentage_format = workbook.add_format()
        percentage_format.set_num_format(10)
        date_format = workbook.add_format({'num_format': 'MM-YYYY'})
        bold_format = workbook.add_format({'bold': True, 'border': True})
        green_format = workbook.add_format({'bg_color': "green"})
        red_format = workbook.add_format({'bg_color': "red"})

        # all columns except for the first date column are money
        worksheet.set_column(1, df.shape[1] - 1, 12, currency_format)

        # create a formula column for net worth. Should be equivalent to dataframe column
        # this is just a form of validation/sanity check
        calcColumn =  df.shape[1]
        worksheet.write_string(0, calcColumn, "net_worth (formula)", bold_format)
        for row in range(2, simulation_length_months + 2):
            rangeStart = 1 # first numerical column after date column
            rangeEnd = rangeStart + len(accounts)
            accountBalanceRange = [columnName(rangeStart), columnName(rangeEnd)]
            rangeStart = rangeEnd + 1
            rangeEnd = rangeStart + len(loans) - 1
            loanBalanceRange = [columnName(rangeStart), columnName(rangeEnd)]
            rangeStart = rangeEnd + 1
            rangeEnd = rangeStart + len(usedAssets) - 1
            assetsValueRange = [columnName(rangeStart), columnName(rangeEnd)]
            rangeStart = rangeEnd + 1
            rangeEnd = rangeStart
            monthlyCostsColumn = columnName(rangeStart)
            rangeStart = rangeEnd + 1
            rangeEnd = rangeStart + len(contributions) - 1
            rangeEnd += 1 # add one for leftover_contribution_account which isn't in the list of fixed contributions
            contributionsRange = [columnName(rangeStart), columnName(rangeEnd)]
            spentColumn =  columnName(rangeEnd + 1)

            # some columns add to net worth (accounts) and some take away (loans & payments)
            formula = "=(SUM({}{}:{}{})-SUM({}{}:{}{})+SUM({}{}:{}{})-{}{}-SUM({}{}:{}{})-{}{})".format(
                accountBalanceRange[0], row, 
                accountBalanceRange[1], row,
                loanBalanceRange[0], row,
                loanBalanceRange[1], row,
                assetsValueRange[0], row,
                assetsValueRange[1], row,
                monthlyCostsColumn, row,
                contributionsRange[0], row,
                contributionsRange[1], row,
                spentColumn, row
            )
            worksheet.write_formula(row-1, calcColumn, formula)

        worksheet.set_column(calcColumn, calcColumn, 12, currency_format)

        # output debug/test parameters
        infoColumn = calcColumn + 2
        worksheet.set_column(infoColumn, infoColumn, 25) # widen columns
        worksheet.set_column(infoColumn + 1, infoColumn + max(len(loans), len(accounts)) + 1, 12) # widen columns

        # simulation parameters
        simParams = ["monthly surplus", "simulation length months", "leftover contribution account"]
        simParamRow = 2
        worksheet.write_string(simParamRow, infoColumn, "Simulation parameters", green_format)
        for i, parm in enumerate(simParams):
            worksheet.write_string(simParamRow + i + 1, infoColumn, parm, bold_format)
        row = simParamRow + 1
        worksheet.write_number(row, infoColumn + 1 , monthly_surplus, currency_format)
        row += 1
        worksheet.write_number(row, infoColumn + 1, simulation_length_months)
        row += 1
        worksheet.write_string(row, infoColumn + 1, leftover_contribution_account)

        # account parameters
        accountParams = ["initial balance", "interest"]
        accountRow = simParamRow + len(simParams) + 2

        worksheet.write_string(accountRow, infoColumn, "Accounts", green_format)
        for i, parm in enumerate(accountParams):
            worksheet.write_string(accountRow + i + 1, infoColumn, parm, bold_format)
        for i, account in enumerate(accounts.values()):
            row = accountRow
            worksheet.write_string(row, infoColumn + 1 + i, account.name, bold_format)
            row += 1
            worksheet.write_number(row, infoColumn + 1 + i, account.initial_balance, currency_format)
            row += 1
            worksheet.write_number(row, infoColumn + 1 + i, account.interest, percentage_format)

        # loan parameters
        loanParams = ["initial balance", "interest", "asset name", "asset value", "asset appreciation", "down payment", "start date", "contributes net worth"]
        loanRow = accountRow + len(accountParams) + 2
        
        worksheet.write_string(loanRow, infoColumn, "Loans", red_format)
        for i, parm in enumerate(loanParams):
            worksheet.write_string(loanRow + i + 1, infoColumn, parm, bold_format)
        for i, loan in enumerate(loans.values()):
            row = loanRow
            worksheet.write_string(row, infoColumn + 1 + i, loan.name, bold_format)
            row += 1
            worksheet.write_number(row, infoColumn + 1 + i, loan.initial_balance, currency_format)
            row += 1
            worksheet.write_number(row, infoColumn + 1 + i, loan.interest, percentage_format)
            row += 1
            worksheet.write_string(row, infoColumn + 1 + i, loan.asset_name)
            row += 1
            worksheet.write_number(row, infoColumn + 1 + i, loan.asset_initial_value, currency_format)
            row += 1
            worksheet.write_number(row, infoColumn + 1 + i, loan.asset_appreciation, percentage_format)
            row += 1
            if(loan.down_payment != None):
                worksheet.write_number(row, infoColumn + 1 + i, loan.down_payment["amount"], currency_format)
            row += 1
            if(loan.start_date != None):
                worksheet.write_datetime(row, infoColumn + 1 + i, loan.start_date, date_format)
            row += 1
            worksheet.write_string(row, infoColumn + 1 + i, str(loan.contributes_net_worth))

        # recurring cost parameters
        costParams = ["amount", "start date", "end date"]
        costRow = loanRow + len(loanParams) + 2

        worksheet.write_string(costRow, infoColumn, "Monthly costs", red_format)
        for i, parm in enumerate(costParams):
            worksheet.write_string(costRow + i + 1, infoColumn, parm, bold_format)
        for i, cost in enumerate(monthlyCosts):
            row = costRow
            worksheet.write_string(row, infoColumn + 1 + i, cost.name, bold_format)
            row += 1
            worksheet.write_number(row, infoColumn + 1 + i, cost.amount, currency_format)
            row += 1
            if(cost.start_date != None):
                worksheet.write_datetime(row, infoColumn + 1 + i, cost.start_date, date_format)
            row += 1
            if(cost.end_date != None):
                worksheet.write_datetime(row, infoColumn + 1 + i, cost.end_date, date_format)
            
    print("exported to ", export_filename)

# Plot graph
fig, ax = plt.subplots()

for name, acc in accounts.items():
    ax.plot(df['date'], df[acc.name], label=acc.name)
for name, loan in loans.items():
    ax.plot(df['date'], df[loan.name], label=loan.name)
    if(loan.asset_name != "" and loan.contributes_net_worth):
        ax.plot(df['date'], df[loan.asset_name], label=loan.asset_name + " value")
for cost in monthlyCosts:
    ax.plot(df['date'], df["monthly_costs"], label="monthly_costs")


ax.plot(df['date'], df["net_worth"], label="net worth")

# Formatting 
ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter('%m/%Y'))
fmt = '${x:,.0f}'
tick = mtick.StrMethodFormatter(fmt)
ax.yaxis.set_major_formatter(tick) 

# Rotate date labels for better readability
plt.xticks(rotation=45)

# Adding labels and title
plt.xlabel('Date')
plt.ylabel('Value')
plt.title('Date / account balance')
plt.legend()

# Display the plot
plt.show()

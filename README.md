# How to not be poor

- Simulate your net worth month to month. 
- Experiment with different ways of allocating your extra income.
- Observe the results of starting a mortgage of different sizes and at different times.
- Generate an Excel file with all the results and compare them with different scenarios.

## How to use
Install Python and use pip to install the dependencies:
- numpy
- pandas
- xlsxwriter
- matplotlib

The simulation is configured using the parameters file. There is no documentation, but all the features are demonstrated in the example. Some fields are required, such as the name and balance of an account, while others are optional. This can be inferred from the examples and code.
  
Always check the output Excel file to ensure that the results make sense. The code will not catch all mistakes. For example if you misspell an account name in your monthly contributions, it won't warn you, it will just not allocate those funds, so be careful.

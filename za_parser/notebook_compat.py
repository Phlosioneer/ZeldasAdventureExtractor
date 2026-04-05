

# Compat for running scripts in both jupyter and console
try:
    display = __builtins__.display
except AttributeError:
    def display(data):
        print(data)

from storage import file_parser, number_of_files, file_reader
print("TESTING...")

data = file_reader("test_proc.prcss")
for x in data:
    print(x)

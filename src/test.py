from storage import file_parser, number_of_files, file_reader, save_success
print("TESTING...")

# data = file_reader("test_proc.prcss")
# for x in data:
#     print(x[0])

file = "AutoFilter_Mechanical_Design.prcss"
label = "<Pull New PN#\n"

save_success(label, file)
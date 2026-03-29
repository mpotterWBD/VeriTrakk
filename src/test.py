from storage import file_parser, number_of_files, file_reader, set_S, has_S, remove_S, save_root, read_root, has_child
print("TESTING...")


# data = file_reader("test_proc.prcss")
# for x in data:
#     print(x[0])

file = "test_proc.prcss"
label = "[S]|TASK #1"


data = file_reader("test_proc.prcss")

for x in data:
    print (x + "Has child? = " + str(has_child(data,x)) + "\n")


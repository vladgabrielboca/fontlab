fontlab-text-shim.so: text-shim.c
	$(CC) -O2 -Wall -Wextra -shared -fPIC -o $@ $< -ldl

clean:
	rm -f fontlab-text-shim.so

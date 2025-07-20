CertUtil -hashfile boot.bin MD5
scp -i c:/users/bunnie/.ssh/id_pi boot.bin pi@10.0.245.90:code/precursors/

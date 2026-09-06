The instances of set Pansart2022 were introduced by [https://arxiv.org/abs/2201.08446](https://arxiv.org/abs/2201.08446).
The authors shared the instances on request.

The format of the instances is:

	P : Number of patient-donor pairs
	N : Number of altruistic donors
	K : Cycle max length
	L : Chain max length
	Matrix M of the medical benefit associated with the exchanges
		The first N rows correspond to the altruistic donors
		The last P rows correspond to the patient-donor pairs
		The P columns correspond to the patient-donor pairs
		Entry M[i,j] = medical benefit associated with the transplantation
		of a kidney of donor i to the patient of patient-donor pair j
		Value -1 means that the corresponding transplantation cannot be realised

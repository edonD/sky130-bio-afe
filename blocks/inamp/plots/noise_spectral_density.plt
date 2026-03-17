set encoding utf8
set termoption noenhanced
set title "Output Noise (V/rtHz)"
set xlabel "Hz"
set ylabel "V/rtHz"
set grid
set logscale x
set xrange [1e-01:1e+03]
set mxtics 10
set grid mxtics
unset logscale y 
set yrange [1.047882e-06:4.271770e-05]
#set xtics 1
#set x2tics 1
#set ytics 1
#set y2tics 1
set format y "%g"
set format x "%g"
plot 'plots/noise_spectral_density.data' using 1:2 with lines lw 1 title "onoise_spectrum"
set terminal push
set terminal png noenhanced
set out 'plots/noise_spectral_density.png'
replot
set term pop
replot

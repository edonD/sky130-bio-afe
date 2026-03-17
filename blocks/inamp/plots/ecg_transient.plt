set encoding utf8
set termoption noenhanced
set title "ECG Transient Output"
set xlabel "s"
set ylabel "V"
set grid
unset logscale x 
set xrange [0.000000e+00:2.000000e+00]
unset logscale y 
set yrange [-6.465790e-02:9.148821e-03]
#set xtics 1
#set x2tics 1
#set ytics 1
#set y2tics 1
set format y "%g"
set format x "%g"
plot 'plots/ecg_transient.data' using 1:2 with lines lw 1 title "vdiff_out"
set terminal push
set terminal png noenhanced
set out 'plots/ecg_transient.png'
replot
set term pop
replot

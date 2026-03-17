set encoding utf8
set termoption noenhanced
set title "CM-to-Diff Gain (dB)"
set xlabel "Hz"
set ylabel "dB"
set grid
set logscale x
set xrange [1e+00:1e+05]
set mxtics 10
set grid mxtics
unset logscale y 
set yrange [-2.766476e+02:-2.105740e+02]
#set xtics 1
#set x2tics 1
#set ytics 1
#set y2tics 1
set format y "%g"
set format x "%g"
plot 'plots/cmrr_vs_freq.data' using 1:2 with lines lw 1 title "cm_gain_db"
set terminal push
set terminal png noenhanced
set out 'plots/cmrr_vs_freq.png'
replot
set term pop
replot

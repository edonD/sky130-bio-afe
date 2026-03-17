set encoding utf8
set termoption noenhanced
set title "Output (zero input)"
set xlabel "s"
set ylabel "V"
set grid
unset logscale x 
set xrange [0.000000e+00:1.425462e-02]
unset logscale y 
set yrange [-5.701412e-11:1.963490e-11]
#set xtics 1
#set x2tics 1
#set ytics 1
#set y2tics 1
set format y "%g"
set format x "%g"
plot 'plots/offset_measurement.data' using 1:2 with lines lw 1 title "vdiff"
set terminal push
set terminal png noenhanced
set out 'plots/offset_measurement.png'
replot
set term pop
replot

set encoding utf8
set termoption noenhanced
set title "Diff Output (1mV in)"
set xlabel "s"
set ylabel "V"
set grid
unset logscale x 
set xrange [0.000000e+00:3.000000e-01]
unset logscale y 
set yrange [-8.951451e-13:9.159978e-12]
#set xtics 1
#set x2tics 1
#set ytics 1
#set y2tics 1
set format y "%g"
set format x "%g"
plot 'plots/dc_gain.data' using 1:2 with lines lw 1 title "vdiff"
set terminal push
set terminal png noenhanced
set out 'plots/dc_gain.png'
replot
set term pop
replot
